# RubriQ

루브릭 기반 영어 Writing 자동 평가 Agent — LangGraph 채점 그래프 + 정량 평가 하네스.

> **개인 프로젝트**입니다. 실무 프로덕션 시스템이 아니며,
> Agent 워크플로우 설계와 정량 평가 파이프라인을 직접 구현하고 측정하기 위해 만들었습니다.

## 지금 상태

측정 체계와 베이스라인 채점기, 관측(Langfuse)까지 구현했습니다.
**골든셋이 없어 실측 숫자는 아직 없습니다** — 확보되는 대로 아래 표를 채웁니다.

진행 이력은 [`docs/WORKLOG.md`](docs/WORKLOG.md), 기능별 기획은 [`docs/features/`](docs/features/).

## 빠른 시작

```bash
uv sync
cp .env.example .env                            # 키 채우기
docker compose -f docker/compose.yaml up -d     # pgvector(:5432), Langfuse v4(:3001)
uv run pytest tests/unit
```

Langfuse UI: http://localhost:3001 — 헤드리스 초기화로 계정·프로젝트·API 키가 기동 시 자동 생성됩니다
(`dev@rubriq.local` / `rubriq-local-dev`). `.env.example`의 키를 그대로 쓰면 됩니다.
포트가 다른 프로젝트와 겹치면 `.env`의 `LANGFUSE_PORT` / `POSTGRES_PORT`만 바꾸면 됩니다.

## 설계

에세이를 받아 루브릭 항목별 점수 + 근거 + 교사용 코멘트를 반환합니다.

```
에세이 → 전처리 → 사전 라우팅(조기 반환)
       → 도구 병렬 호출 (grammar_check · lexical_stats · retrieve_anchors)
       → 항목별 병렬 채점 (본문 근거 인용 강제)
       → 일관성 검증 ─모순→ 재채점 루프(≤2회) ─초과→ needs_human_review
       → 피드백 생성 → Pydantic 검증 → 스트리밍 응답
```

설계 근거와 트레이드오프는 [`docs/00-설계.md`](docs/00-설계.md) §1과 [`docs/adr/`](docs/adr/)에 있습니다.
기능 단위 기획은 [`docs/features/`](docs/features/)에 17개 문서로 정리했습니다 —
각각 **문제 → 계약 → 설계 → 핵심 결정 → 실패 모드 → 측정** 형식입니다.

## 측정

| 지표 | 값 |
|---|---|
| QWK (vs 인간 채점) | _미측정_ |
| 인접 정확도 (±1) | _미측정_ |
| 일관성 σ (동일 입력 5회) | _미측정_ |
| 오류 탐지 P/R/F1 | _미측정_ |
| p50 / p95 latency | _미측정_ |
| 에세이당 비용 | _미측정_ |

before/after 비교는 [`docs/results/`](docs/results/), 실패 사례는 [`docs/failures/`](docs/failures/).

## 한계

- 골든셋 50~100건 규모. 통계적 유의성이 아니라 **회귀 감지**가 목적입니다.
- 파인튜닝·Speaking 평가·프론트엔드는 의도적으로 범위 밖입니다 (근거는 [설계 문서 §6](docs/00-설계.md)).
