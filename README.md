# RubriQ

**영어 에세이 자동 채점기.** 학생이 쓴 영어 글을 넣으면, 6가지 기준으로 각각
1~5점을 매기고 **왜 그 점수인지 본문을 인용해** 돌려줍니다.

```
입력   "Learning a second language is difficult but rewarding.
        When I started studying English, I could not order food..."

출력   Grammar      3점   "she explain the lesson good"  → 시제·품사 오류가 반복되나
                          전반적 이해는 가능
       Vocabulary   3점   "very kind", "good"           → 기본 어휘로 의미는 전달하나
                          정밀도가 낮음
       ... (6개 항목)

       교사용 코멘트 + 사람 검토가 필요한지 여부
```

6가지 기준은 **응집성 · 문장구조 · 어휘 · 관용표현 · 문법 · 표기**이고,
이렇게 "무엇을 보고, 각 점수가 무슨 뜻인지" 미리 적어둔 채점 기준표를
**루브릭(rubric)** 이라고 부릅니다. → [루브릭이 뭔가요](docs/learning/01-루브릭.md)

## 그래서 뭐가 어려운가

채점은 주관적입니다. 같은 글을 두 교사가 다르게 채점하고, **같은 LLM도 돌릴 때마다
다른 점수를 냅니다.** 그래서 "프롬프트를 고쳤더니 좋아졌다"는 말은 측정 없이는
그냥 느낌입니다.

이 프로젝트는 **그 측정 체계를 먼저 만들고** 그 위에서 채점기를 개선합니다.
지표·평가 하네스·회귀 게이트가 채점기보다 먼저 구현된 이유입니다.

> **개인 프로젝트**입니다. 실무 프로덕션 시스템이 아니며,
> Agent 워크플로우 설계와 정량 평가 파이프라인을 직접 구현하고 측정하기 위해 만들었습니다.

## 지금 상태

측정 체계 · 베이스라인 채점기 · 관측(Langfuse) · 골든셋 50건까지 갖췄습니다.
루브릭은 ELLIPSE 공식 루브릭과 대조해 검증했습니다.
**남은 것은 LLM API 키뿐입니다** — 붙는 즉시 아래 표가 채워집니다.

진행 이력은 [`docs/WORKLOG.md`](docs/WORKLOG.md), 기능별 기획은 [`docs/features/`](docs/features/).

## 빠른 시작

```bash
uv sync
cp .env.example .env                            # 키 채우기
docker compose -f docker/compose.yaml up -d     # pgvector(:5432), Langfuse v4(:3001)
uv run pytest                                   # 단위 테스트 — LLM 호출 없음
```

### 💰 과금되는 명령

과금 경로는 두 개뿐이고 둘 다 실행 전에 막혀 있습니다 — 자세한 내용은
[`docs/COSTS.md`](docs/COSTS.md).

```bash
# 0원 — 비용만 확인 (API 키도 필요 없음)
uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl --dry-run

# 💰 유료 — 비용 추정을 보여주고 확인을 받습니다
uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl --limit 5

# 💰 유료 — RUBRIQ_ALLOW_PAID=1 없이는 skip 됩니다
RUBRIQ_ALLOW_PAID=1 uv run pytest -m regression
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
| QWK (vs 인간 채점) | _미측정 — LLM API 키 필요_ |
| 인접 정확도 (±1) | _미측정_ |
| 일관성 σ (동일 입력 5회) | _미측정_ |
| 오류 탐지 P/R/F1 | _미측정_ |
| p50 / p95 latency | _미측정_ |
| 에세이당 비용 | _미측정_ |

before/after 비교는 [`docs/results/`](docs/results/), 실패 사례는 [`docs/failures/`](docs/failures/).

## 한계

- 골든셋 50~100건 규모. 통계적 유의성이 아니라 **회귀 감지**가 목적입니다.
- 파인튜닝·Speaking 평가·프론트엔드는 의도적으로 범위 밖입니다 (근거는 [설계 문서 §6](docs/00-설계.md)).
