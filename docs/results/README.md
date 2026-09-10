# 측정 결과

**측정 없는 개선은 주장이다.** 모든 변경은 여기에 before/after 표로 남는다.

| 파일 | 내용 |
|---|---|
| `01-baseline.md` | T0 단일 프롬프트 베이스라인 성능표 |
| `02-agent-vs-baseline.md` | LangGraph Agent vs 베이스라인 |
| `03-prompt-v1-vs-v2.md` | 프롬프트 개선 전후 (동일 골든셋) |
| `04-model-routing.md` | 항목별 모델 배분 — 비용 · QWK 트레이드오프 |
| `05-prompt-caching.md` | 루브릭 정의부 캐싱 전후 비용 · latency |

공통 표 형식:

| 지표 | before | after | Δ |
|---|---|---|---|
| QWK (전체) | | | |
| 인접 정확도 | | | |
| 일관성 σ (5회 반복) | | | |
| 오류 탐지 F1 | | | |
| p50 / p95 latency | | | |
| 에세이당 비용 | | | |

측정 조건(모델·temperature·골든셋 파일·커밋 해시)을 표 위에 반드시 적는다.
