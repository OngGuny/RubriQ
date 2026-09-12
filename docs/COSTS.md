# 💰 돈이 나가는 행동

이 저장소에서 **과금되는 경로는 두 개뿐**이다. 둘 다 실행 전에 막혀 있다.

| | 경로 | 차단 장치 |
|---|---|---|
| 1 | `scripts/run_eval.py` | 비용 추정 출력 → **확인 프롬프트** |
| 2 | `uv run pytest -m regression` | 마커 제외 + **환경변수 오프트인** |

그 외는 전부 무료다 — Langfuse(self-host), Kaggle, `count_tokens`, 단위 테스트.

---

## 1. 골든셋 채점 — `scripts/run_eval.py`

```bash
# 💸 0원 — 비용만 보고 끝낸다. API 키도 필요 없다
uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl --dry-run

# 💰 유료 — 확인 프롬프트가 뜬다
uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl --limit 5
```

실행 순서:

1. 골든셋 로드 (무료)
2. `--dry-run`이면 추정만 출력하고 종료 — **키 없이도 동작한다**
3. 클라이언트 생성 — 키가 없으면 여기서 끝난다
4. `count_tokens`로 입력 토큰 실측 (**무과금**)
5. 비용 추정 출력 → **`진행할까요? [y/N]`**
6. `y`가 아니면 중단. 호출 0회, 비용 0원

**기본값이 '아니오'다.** 엔터만 치면 진행하지 않는다.
비대화 환경(파이프·CI)에서는 물을 수 없으므로 **중단한다** — 조용히 돈을 쓰지 않는다.

## 2. 회귀 테스트 — `pytest -m regression`

pytest는 대화형 확인을 받을 수 없다. 그래서 **두 겹**으로 막았다.

```bash
uv run pytest                          # 💸 regression 제외됨 (addopts)
uv run pytest -m regression            # 💸 skip — 오프트인 없음
RUBRIQ_ALLOW_PAID=1 uv run pytest -m regression   # 💰 유료
```

`RUBRIQ_ALLOW_PAID`는 **`1`만** 인정한다. `true`나 `0`은 우회가 아니다.

---

## 확인 건너뛰기 (CI용)

| 방법 | 용도 |
|---|---|
| `--yes` / `-y` | `run_eval.py` 단발 실행 |
| `RUBRIQ_ALLOW_PAID=1` | 양쪽 모두 |

**사람이 없는 환경에서만 쓴다.** GitHub Actions의 `regression` 잡이
`workflow_dispatch` 수동 트리거인 이유가 이것이다 — 푸시마다 돌지 않는다.

---

## 비용 구조

| 항목 | 토큰 | 캐시 |
|---|--:|---|
| system 블록 (루브릭) | ~1,400 | ⭕ 대상 |
| 구조화 출력 스키마 | ~295 | ❌ `output_config`는 프리픽스 밖 |
| 에세이 (중앙값) | ~510 | ❌ 가변 |
| **출력 + thinking** | **?** | — |

**출력이 비용의 대부분이다.** `effort=medium`의 adaptive thinking이
호출 전에는 몇 토큰일지 알 수 없다. 그래서 추정을 구간으로 보여준다.

입력은 `count_tokens`로 정확히 세지만(무과금), 출력은 셀 방법이 없다.
→ **소규모(`--limit 5`)로 실측한 뒤 역산**하는 것이 유일한 방법이다.

### 현재 추정 (Claude Opus 5, 캐싱 on)

| 규모 | 낙관 (출력 2K) | 비관 (출력 6K) |
|---|--:|--:|
| 5건 | ~$0.28 | ~$0.78 |
| 50건 | ~$2.77 | ~$7.77 |

실측이 나오면 이 표를 `docs/results/01-baseline.md`의 실제 숫자로 교체한다.

### 시간도 비용이다

하네스는 **순차 호출**이다. thinking 포함 호출이 30~60초면 50건에 25~50분이다.
병렬화는 F13(항목별 병렬 채점)에서 도입한다.

---

## 앞으로 유료가 될 경로

아직 구현 전이지만 미리 표시해 둔다.

| 기능 | 과금 | 대비 |
|---|---|---|
| F12 앵커 검색 | **임베딩 API** — 앵커 적재 시 코퍼스 전체 임베딩 | `scripts/ingest_anchors.py`에 같은 게이트를 붙일 것 |
| F13 항목별 병렬 채점 | 호출이 **6배** | 캐싱으로 상쇄. 게이트에 항목 수 반영 필요 |
| F14 재채점 루프 | 모순 시 **추가 호출** (최대 2회) | 추정에 루프 상한을 곱해야 정확해진다 |
| F16 모델 라우팅 | 벤더 추가 시 OpenAI 등 | 요금표(`llm/base.py:PRICING`)에 추가 |

> **현재 추정은 재채점 루프를 반영하지 않는다.** F14가 붙으면
> 최악의 경우 채점 호출이 3배가 될 수 있다 (1차 + 재채점 2회).

---

## 잔여 위험 — 게이트를 우회하는 경로

**애드혹 스크립트는 게이트를 거치지 않는다.**

```python
SinglePromptGrader().grade(essay)   # 💰 확인 없이 바로 호출한다
```

`SinglePromptGrader`에 `llm`을 안 주면 실제 `AnthropicStructuredLLM`이 붙는다.
비용 게이트는 `scripts/run_eval.py`에 있고, 이 경로에는 없다.
키가 없을 때 `MissingCredentials`로 막히는 것이 **유일한 자동 방어**다.

같은 구조적 문제를 실제로 관측했다 — 검증용 애드혹 스크립트가 전역 트레이서를 잡아
Langfuse에 트레이스 50건을 보냈다. Langfuse는 무료라 비용은 없었지만,
**같은 경로로 LLM을 불렀다면 돈이 나갔을 것이다.**

대응은 두 가지다:

1. 애드혹 실행에서는 `FakeLLM`이나 오라클을 **명시적으로 주입**한다
2. 실제 호출이 필요하면 `scripts/run_eval.py --limit N`을 쓴다 — 게이트가 붙어 있다

`AnthropicStructuredLLM`의 docstring에 💰 표시를 달아 읽는 사람이 알 수 있게 했다.
자동 차단이 아니라 표시일 뿐이라는 점을 분명히 해 둔다.

## 무료인 것

- **Langfuse** — self-host (`docker compose`). 단, `LANGFUSE_HOST`를
  cloud.langfuse.com으로 바꾸면 유료 티어가 될 수 있다. 기본값은 `localhost:3001`.
- **Kaggle** — 데이터 다운로드는 무료. 이미 로컬에 있어 재다운로드도 불필요.
- **`count_tokens`** — 과금되지 않는다. 레이트 리밋만 소모한다.
- **단위 테스트 146건** — LLM·네트워크를 타지 않는다.
  `tests/conftest.py`의 autouse fixture가 트레이서까지 비활성화한다.

## 게이트를 믿을 수 있는가

`tests/unit/test_preflight.py` 18건이 **막아야 할 때 막는지**를 확인한다 —
거부·엔터·무관한 답·비대화 환경 전부 중단되는지.

게이트를 무력화하는 뮤테이션을 넣어 **정확히 5건이 깨지는 것**을 확인했다.
게이트가 통과하는 걸 확인하는 건 검증이 아니다.
