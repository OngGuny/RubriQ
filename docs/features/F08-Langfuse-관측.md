# F08. Langfuse 관측 · 트레이싱

| | |
|---|---|
| 상태 | **구현됨** — 로컬 스택에서 트레이스 수집 확인 |
| 단계 | T0 |
| 코드 | `src/rubriq/observability/langfuse.py` · `tests/unit/test_observability.py` (22건) |
| 의존 | F05 LLM 클라이언트 · F04 프롬프트 레지스트리 |
| 인프라 | `docker/compose.yaml` — Langfuse v4 (web · worker · postgres · clickhouse · redis · minio) |
| 관련 | ADR 004 |

## 문제

숫자가 나빠졌을 때 **어디서 무너졌는지** 알아야 한다.
최종 점수만 보면 전처리가 문제인지, 도구 출력이 이상한지, 채점 프롬프트가 문제인지 모른다.

## 계약

```
요청 1건 = trace 1개
  grade:{essay_id}                span
    └ score:all-dimensions        generation   ← 베이스라인 (1회 호출)
```

T1 이후 그래프가 생기면 노드마다 span이 붙고, 항목별 채점이 generation 6개로 갈린다.

각 generation에 기록되는 것:

| 필드 | 값 |
|---|---|
| `metadata.prompt_id` | `scoring@v1` |
| `metadata.prompt_fingerprint` | 내용 SHA256 앞 12자 |
| `metadata.cache_hit` | `cache_read_tokens > 0` |
| `metadata.latency_ms` | 호출 지연 |
| `usage_details` | input · output · **cache_read** · cache_creation |
| `cost_details.total` | 요금표 기반 USD |

## 설계 — 호출부를 고치지 않는다

`TracedLLM`이 `StructuredLLM` 프로토콜을 그대로 구현하는 데코레이터다.
채점기는 자기가 트레이싱되는지 모른다.

```
SinglePromptGrader → TracedLLM → AnthropicStructuredLLM
                        │
                        └→ Langfuse
```

프롬프트 버전 같은 메타데이터는 **contextvar**로 흘린다.
`StructuredLLM` 프로토콜에 인자를 추가하는 것보다 결합이 약하다 —
프로토콜은 프롬프트 버전을 알 필요가 없다.

## 핵심 결정 1 — 관측이 본 기능을 죽이지 않는다

| 실패 | 처리 |
|---|---|
| 키 없음 | 비활성 트레이서. **로그에 남김** |
| 인증 실패 | 비활성 트레이서. 기동 시점에 경고 |
| 서버 죽음 | 비활성 트레이서 (연결 시도 후 판정) |
| span 시작 실패 | `None` 반환, 채점 계속 |
| `update()` 실패 | 삼킴, 채점 계속 |

`build_tracer()`가 기동 시점에 `auth_check()`를 한 번 돌린다.
키가 틀렸으면 채점 도중이 아니라 **시작할 때** 알아야 한다.

> 조용히 꺼진 관측은 없는 것보다 나쁘다. 그래서 비활성화는 반드시 로그에 남는다.

## 핵심 결정 2 — 무엇을 남기지 않을지 먼저 정한다

에세이 본문은 **학생 저작물**이다. 기본값은 남기지 않는다.

```python
payload = {"system_chars": 3878, "user_chars": 412}   # 기본
payload = {"system": "...", "user": "..."}            # record_prompt=True
```

트레이스에는 `essay_id`와 통계(길이·단어 수)만 남는다.
`essay_id`로 원본을 되찾을 수 있으므로 학생 글을 관측 저장소에 복제할 이유가 없다.
지금은 공개 데이터셋만 쓰지만 **처음부터** 이렇게 정해뒀다.

## 핵심 결정 3 — 캐시 토큰을 반드시 남긴다

`usage_details.cache_read_input_tokens`가 0인지 보는 것이
**캐싱이 실제로 먹는지 확인하는 유일한 수단**이다. 캐시 미스는 에러를 내지 않는다.
F16 비용 튜닝이 전적으로 이 값에 의존한다.

## 실제로 확인한 것

로컬 스택에 채점 1건을 흘려 ClickHouse까지 도달을 확인했다.

```
name                   type         cost
grade:e-smoke-001      SPAN         0
score:all-dimensions   GENERATION   0.00704
```

## 밟은 함정 — 테스트가 실제 Langfuse를 오염시켰다

`.env`에 키가 생기자 `get_tracer()`가 진짜 클라이언트를 만들어
**단위 테스트가 로컬 Langfuse로 트레이스를 보내기 시작했다.**
`grade:e-001` 트레이스 5건이 실제로 쌓였다.

대응: `tests/conftest.py`에 autouse fixture로 트레이서를 강제 비활성화한다.
트레이싱을 검증하는 테스트는 가짜 트레이서를 **명시적으로 주입**한다.

검증 방법도 고정했다 — 테스트 실행 전후 ClickHouse 이벤트 수가 같은지 본다.

> 테스트가 밀폐(hermetic)되지 않으면, 테스트를 돌릴 때마다 관측 데이터가 더러워진다.
> 그러면 트레이스를 믿을 수 없게 되고, 관측의 목적 자체가 사라진다.

## 남은 것

- **프롬프트를 Langfuse에 등록하지 않았다.** 현재는 파일이 원본이고 트레이스에는
  식별자·지문만 남는다. 버전별 성능 비교는 지문으로 가능하지만,
  Langfuse 프롬프트 관리 기능은 아직 안 쓴다.
- `<!-- CACHE_BOUNDARY -->` 마커를 어떻게 등록할지 미정
  (원문 그대로 vs 두 블록 분리).
- **완료 조건은 아직 미달.** "트레이스를 붙였다"가 아니라
  "트레이스로 원인을 찾았다"가 이 기능의 완료다.
  `docs/failures/` 3건을 쓸 때 판명된다.
