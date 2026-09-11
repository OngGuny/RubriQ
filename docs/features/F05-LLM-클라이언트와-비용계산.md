# F05. LLM 클라이언트 · 비용 계산

| | |
|---|---|
| 상태 | **구현됨** (실제 API 미호출) |
| 단계 | T0 |
| 코드 | `src/rubriq/llm/base.py` · `anthropic_client.py` |
| 의존 | F01 데이터 계약 |

## 문제

- 벤더를 직접 호출하면 F16 모델 라우팅에서 호출부를 전부 고쳐야 한다.
- **에세이당 비용**이 필수 지표인데, 토큰 사용량을 나중에 붙이면 역시 전부 고쳐야 한다.

## 계약

```python
class StructuredLLM(Protocol):
    def complete[T: BaseModel](
        self, *, cacheable_system: str, user_content: str, schema: type[T]
    ) -> LLMResult[T]: ...

LLMResult: output · model · usage · latency_ms · cost_usd
TokenUsage: input · output · cache_read · cache_write  (+ cache_hit)
```

**관측값을 응답에 같이 실어 나른다.** 비용·지연·캐시 히트가 호출 결과의 일부다.

## 설계

| 요소 | 선택 | 근거 |
|---|---|---|
| 구조화 출력 | `client.messages.parse(output_format=<Pydantic>)` | SDK가 스키마 검증까지 해준다 |
| 고정부 위치 | `system` | 렌더 순서가 tools → system → messages라 여기까지가 프리픽스 |
| 캐시 마커 | system 끝에 `cache_control` | 경계를 명시 |
| 사고 | adaptive + `effort` 설정 | effort 스윕 자체가 측정 대상 |

## 핵심 결정 1 — 요금표에 없으면 예외

```python
estimate_cost_usd("gpt-9", usage)  # → UnknownModelPricing
```

모르는 모델의 비용을 0으로 계산하면 **"비용 절감했다"는 잘못된 결론**이 나온다.

## 핵심 결정 2 — refusal fallback을 쓰지 않는다

문서상 `claude-opus-5` 기본 권장이지만 `client.beta.messages` 경로라
`parse()`의 스키마 검증과 조합이 문서화돼 있지 않다.
에세이 채점은 거부 표면이 사실상 없고, 이 프로젝트에선 **스키마 검증이 더 중요하다.**
거부가 실제로 관측되면 그때 도입한다.

## 실패 모드

| 상황 | 처리 |
|---|---|
| `stop_reason == "refusal"` | `RefusalError` — content 읽기 전에 확인 |
| `parsed_output is None` | `SchemaViolationError` (max_tokens 초과 의심) |
| 미등록 모델 비용 요청 | `UnknownModelPricing` |

## 측정

캐시 적용 시 절감 예시 — 입력 10K·출력 2K를 Opus 5로 돌릴 때
전량 미캐시 $0.100 → 9K 캐시 히트 $0.060 (**40% 절감**).

## 검증되지 않은 구간

**API 키가 없어 실제 호출을 한 번도 못 했다.** 테스트는 전부 `FakeLLM` 기반이라
배선은 검증됐지만 SDK 호출 자체는 미검증이다.
