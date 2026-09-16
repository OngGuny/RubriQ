# RubriQ — 루브릭 기반 영어 Writing 자동 평가 Agent

루브릭 기반 영어 Writing 자동 평가 파이프라인 — 개인 프로젝트.
설계 문서: `docs/00-설계.md` — 범위·근거·계획의 단일 진실 공급원(SSOT).
설계 문서와 코드가 어긋나면 **설계 문서를 고치고 나서** 코드를 고친다.

## 이 프로젝트가 증명하려는 것

SOTA 채점기가 아니다. **측정 가능(measurable)하고 관측 가능(observable)한 Agent 파이프라인**을
직접 돌려봤다는 증거를 만드는 것이 목표다. 추상론이 아니라 숫자로 말하기 위한 프로젝트다.

## 작업 원칙 (이 프로젝트에서 특히 중요)

1. **측정 없는 개선은 주장이다.** 프롬프트·모델·그래프를 건드렸으면 골든셋을 재측정하고
   `docs/results/`에 before/after 표를 남긴다. 숫자 없이 "개선했다"고 쓰지 않는다.
2. **정직성.** 포트폴리오 프로젝트다. README·문서 어디에도 실무 경험처럼 포장하지 않는다.
   한계와 실패는 `docs/failures/`에 먼저 쓴다. 약점을 먼저 말하는 것이 이 프로젝트의 자산이다.
3. **설계 결정은 ADR로.** "왜 이렇게 했나"를 나중에 재구성할 수 없다. 구조적 선택을 할 때마다
   `docs/adr/NNN-*.md` 한 장을 남긴다 (맥락 / 선택지 / 결정 / 트레이드오프).
4. **실패를 숨기지 않는다.** 모순이 안 잡히면 `needs_human_review` 플래그를 세워 반환한다.
   교육 도메인에서는 그럴듯한 오답보다 "모르겠다"가 안전하다.
5. **범위 방어.** `docs/00-설계.md` §6의 "의도적으로 하지 않는 것"을 임의로 늘리지 않는다.
   (파인튜닝 / Speaking / 프론트엔드 / 자동 재학습)

6. **답할 수 없는 질문을 남기지 않는다.** `docs/09-예상질문.md`는 이 프로젝트가
   답해야 하는 기술 질문 목록이고, 각 질문 옆에 **답이 있는 문서 경로**를 적는다.
   경로가 비면 그건 문서가 부족한 것이다. 기능을 끝낼 때 관련 질문에 경로가
   채워졌는지 확인한다. **답 자체를 그 파일에 적지 않는다** — 문서가 원본이다.

7. **작업이 끝나면 즉시 커밋하고 이력을 남긴다.** 다음 턴으로 미루지 않는다.
   - `docs/WORKLOG.md` 맨 아래에 **append** 한다 (기존 엔트리는 수정하지 않는다).
   - 엔트리는 5줄 내외 — 한 것 / 막힌 것 / 다음. 설계 근거는 반복하지 말고
     `docs/adr/`·`docs/features/`를 **가리키기만** 한다.
   - 목적은 다음 세션이 이 파일만 읽고 바로 이어받는 것이다.

8. **모르는 개념은 넘어가지 않는다.** 사용자가 개념을 물으면, 답만 하지 말고
   `docs/learning/NN-개념.md`에 노트로 남기고 `docs/learning/README.md` 목록을 갱신한다.
   설명은 **정의 나열이 아니라 문제 → 해결 → 이 프로젝트에서 왜 필요한가 → 함정** 순으로 쓴다.
   구현 중 새 용어를 도입할 때도 목록에 제목만이라도 올린다.

## 아키텍처

```
에세이 → [전처리] → [사전 라우팅: 조기 반환 분기]
       → [도구 병렬 호출: grammar_check · lexical_stats · retrieve_anchors]
       → [루브릭 항목별 병렬 채점 (근거 인용 강제)]
       → [일관성 검증] --모순--> [재채점 루프 ≤2회] --초과--> needs_human_review
       → [피드백 생성: 학년×과제유형] → [Pydantic 검증·복구] → 스트리밍 응답
```

핵심 설계 근거 (설계 문서 §1에 상세):
- 항목을 **분리 호출**하는 이유: 한 번에 채점하면 항목 간 점수가 오염된다. 대가는 토큰 비용,
  상쇄 수단은 프롬프트 캐싱.
- **도구 호출**을 쓰는 이유: 오류 카운트 같은 결정적 사실은 규칙 기반 도구가 뽑고,
  LLM은 **판단만** 한다.
- **재채점 상한 2회**: 수렴 보장이 없고 latency가 폭발한다.

## 폴더 구조

```
docs/
  00-설계.md     범위·근거·계획 (SSOT)
  01-루브릭.md   채점 기준 — 프롬프트의 원본. **원본 대조 전까지 미검증 상태**
  WORKLOG.md     작업 이력 — 작업이 끝날 때마다 append. 다음 세션의 출발점
  09-예상질문.md 이 프로젝트가 답할 수 있어야 하는 질문 — 답은 다른 문서에 있어야 한다
  COSTS.md       💰 과금되는 행동 전부와 차단 장치
  learning/      학습노트 — 처음 만난 개념 정리. 모르는 단어가 나오면 여기에 추가한다
  adr/           설계 결정 기록 — 맥락/선택지/결정/트레이드오프
  results/       측정 결과 before/after 표
  failures/      실패 사례 분석 (최소 3건)
src/rubriq/
  schemas.py     Pydantic 스키마 (Essay, RubricScore, GradingResult)
  config.py      pydantic-settings 기반 설정
  prompts/       프롬프트 템플릿 + Langfuse 등록 레지스트리
  llm/           멀티 벤더 클라이언트 · 모델 라우팅 · 프롬프트 캐싱
  tools/         grammar_check / lexical_stats / retrieve_anchors
  graph/         LangGraph 상태·노드·엣지·빌더
  baseline/      T0 단일 프롬프트 베이스라인 (Agent와의 비교 대상, 지우지 말 것)
  observability/ Langfuse 연동
  api/           FastAPI async 서빙 (T2)
eval/
  metrics.py     QWK · 인접 정확도 · 일관성 σ · P/R/F1 · latency
  harness.py     골든셋 러너
  golden/        골든셋 jsonl (+ LICENSE.md 필수)
  reports/       실행 산출물 (git 추적, 시계열로 쌓임)
tests/
  unit/          도구·스키마·메트릭 단위 테스트
  regression/    골든셋 재평가 — QWK가 임계치 아래로 떨어지면 fail
scripts/         골든셋 구축 · 앵커 적재 · 평가 실행 CLI
docker/          compose.yaml (postgres+pgvector, Langfuse) · Dockerfile
```

## 기술 스택

| 영역 | 선택 |
|---|---|
| 패키지 | **uv** (`uv sync`, `uv run`) — pip/poetry 명령 쓰지 않는다 |
| Agent | LangGraph |
| 관측 | Langfuse (self-host, docker compose) |
| 스키마 | Pydantic v2 |
| 서빙 | FastAPI (async) |
| 벡터 | pgvector (postgres 16) |
| 테스트 | pytest + GitHub Actions |
| 문법 도구 | LanguageTool (로컬) 또는 규칙 기반 |
| 모델 | Anthropic + 추가 벤더 1종 (라우팅 비교용) |

## 자주 쓰는 명령

```bash
uv sync                          # 의존성 설치
docker compose -f docker/compose.yaml up -d   # postgres+pgvector(:5432), Langfuse(:3001)
uv run pytest                     # 단위 테스트 — LLM 호출 없음
uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl --dry-run   # 비용만
uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl --limit 5   # 💰
RUBRIQ_ALLOW_PAID=1 uv run pytest -m regression                                  # 💰
uv run ruff check . && uv run ruff format .
```

## 💰 과금되는 행동 — 물어보고 나서 실행한다

과금 경로는 둘뿐이다: `scripts/run_eval.py`, `pytest -m regression`.
전체 목록과 차단 장치는 `docs/COSTS.md`.

**새로 과금 경로를 만들면 반드시 게이트를 붙인다** — `eval/preflight.confirm_or_abort`.
게이트 없는 유료 경로를 추가하지 않는다. 특히 F12 앵커 적재(임베딩 API)가 해당된다.

사용자에게 유료 실행을 제안할 때는 **먼저 `--dry-run`으로 비용을 보여주고 확인을 받는다.**
"돌려볼까요?"가 아니라 "$N 들고 M분 걸립니다. 돌릴까요?"로 묻는다.

## 컨벤션

- **비용 주의**: `tests/regression`은 실제 LLM을 호출한다. `-m regression` 마커로 분리하고,
  추가로 `RUBRIQ_ALLOW_PAID=1` 오프트인이 없으면 skip 한다.
- **프롬프트는 코드에 하드코딩하지 않는다.** `src/rubriq/prompts/templates/`에 두고
  Langfuse에 버전 등록한다. 프롬프트를 고치면 버전을 올리고 재측정한다.
- **시크릿은 `.env`.** `.env.example`만 커밋한다. 실제 키는 절대 커밋 금지.
- **골든셋 라이선스**를 `eval/golden/LICENSE.md`에 명시한다. 상업적 사용 제한이 있으면
  원문 데이터는 커밋하지 않고 지표만 인용한다.
- 타입 힌트 필수. 공개 함수에는 한 줄 docstring.

## 진행 상태

- [ ] **T0** 골든셋 50건 · 베이스라인 채점기 · 평가 하네스 · Langfuse 연동 · 베이스라인 성능표
- [ ] **T1** LangGraph 그래프 · 도구 3종 · 일관성 검증 루프 · 프롬프트 v1→v2 재측정 · 회귀 CI
- [ ] **T2** 모델 라우팅 · 프롬프트 캐싱 · FastAPI 스트리밍 · Teachers Comment · Docker/README

체크박스는 **실제로 돌려보고 숫자가 나왔을 때만** 체크한다.

### 한 작업의 '완료' 정의
1. 코드가 돌아간다 (테스트 통과)
2. 숫자가 `docs/results/`에 기록됐다 (해당되면)
3. 설계 선택이 있었다면 `docs/adr/`에 한 장 남았다
4. **커밋이 남았고 `docs/WORKLOG.md`에 한 줄 붙었다**
