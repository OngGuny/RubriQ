"""T0 베이스라인 채점기 — LLM 1회 호출로 6개 항목을 한꺼번에 채점한다.

**이건 일부러 만든 허수아비다.** 설계 문서 §1가 말하는 "한 번에 채점하면 항목 간 점수가
오염된다"를 실제 숫자로 보여주기 위한 비교 대상이다. T1의 LangGraph 채점기가
이걸 이겨야 분리 호출의 근거가 주장이 아니라 측정이 된다.

**지우지 말 것.** 비교 대상이 없으면 개선폭을 말할 수 없다.

캐싱 메모: system 블록(루브릭)은 약 900토큰이라 Claude Opus 5의 최소 캐시 프리픽스
512토큰을 넘는다. 다만 이 최소값은 모델마다 다르고 세대 순도 아니다 —
Haiku 4.5는 4096토큰이라 **같은 프롬프트가 조용히 캐시되지 않는다.**
T2에서 항목을 경량 모델로 라우팅할 때 캐시 이득이 사라질 수 있다는 뜻이라,
라우팅 비용 계산에 이걸 반드시 포함해야 한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rubriq.llm.anthropic_client import AnthropicStructuredLLM
from rubriq.llm.base import LLMResult, StructuredLLM
from rubriq.prompts.registry import Prompt, load_prompt
from rubriq.schemas import (
    ALL_DIMENSIONS,
    DimensionScore,
    Essay,
    Evidence,
    GradingResult,
    RubricDimension,
    ungrounded_evidence,
)


class LLMDimensionScore(BaseModel):
    """LLM이 항목 하나에 대해 내놓는 원시 출력.

    `GradingResult`와 달리 점수 범위 제약(ge/le)을 걸지 않았다. 의도적이다 —
    JSON 스키마 제약으로 모델을 묶는 대신, 범위를 벗어난 값을 **관측**하고 싶다.
    검증은 `DimensionScore`로 변환할 때 걸린다.
    """

    dimension: RubricDimension
    score: int = Field(description="Integer from 1 to 5")
    evidence_quotes: list[str] = Field(description="Verbatim quotes from the essay")
    rationale: str


class LLMGradingOutput(BaseModel):
    """LLM 응답 전체. 6개 항목이 다 와야 하지만 강제하지 않고 관측한다."""

    scores: list[LLMDimensionScore]


class GradingError(RuntimeError):
    """채점 결과를 유효한 `GradingResult`로 만들 수 없었다."""


class SinglePromptGrader:
    """단일 프롬프트 베이스라인. `Grader` 프로토콜을 구현한다."""

    def __init__(
        self,
        llm: StructuredLLM | None = None,
        *,
        prompt: Prompt | None = None,
        check_grounding: bool = True,
    ) -> None:
        """
        Args:
            check_grounding: 인용문이 원문에 실재하는지 대조한다.
                할루시네이션된 근거를 발견하면 점수는 유지하되 human review로 넘긴다.
                점수까지 버리지 않는 이유는, 근거가 부실해도 점수 자체는 맞을 수 있고
                그 판단은 사람이 하는 게 맞기 때문이다.
        """
        self._llm = llm or AnthropicStructuredLLM()
        self._prompt = prompt or load_prompt("scoring", "v1")
        self._check_grounding = check_grounding
        self.last_result: LLMResult[LLMGradingOutput] | None = None

    @property
    def prompt_id(self) -> str:
        return self._prompt.id

    def grade(self, essay: Essay) -> GradingResult:
        result = self._llm.complete(
            cacheable_system=self._prompt.system,
            user_content=self._prompt.render_user(essay.text),
            schema=LLMGradingOutput,
        )
        self.last_result = result
        return self._to_grading_result(essay, result)

    def _to_grading_result(
        self, essay: Essay, result: LLMResult[LLMGradingOutput]
    ) -> GradingResult:
        raw = result.output
        by_dim = {s.dimension: s for s in raw.scores}

        missing = [d.value for d in ALL_DIMENSIONS if d not in by_dim]
        if missing:
            raise GradingError(f"{essay.essay_id}: 누락된 항목 {missing}")
        if len(raw.scores) != len(ALL_DIMENSIONS):
            dupes = sorted({s.dimension.value for s in raw.scores if raw.scores.count(s) > 1})
            raise GradingError(f"{essay.essay_id}: 항목 개수 이상 (중복 후보 {dupes})")

        scores: list[DimensionScore] = []
        for dim in ALL_DIMENSIONS:
            item = by_dim[dim]
            if not 1 <= item.score <= 5:
                raise GradingError(f"{essay.essay_id}: {dim.value} 점수 {item.score}가 1~5 범위 밖")
            quotes = [q for q in item.evidence_quotes if q.strip()]
            if not quotes:
                raise GradingError(f"{essay.essay_id}: {dim.value}에 근거 인용이 없다")
            scores.append(
                DimensionScore(
                    dimension=dim,
                    score=item.score,
                    rationale=item.rationale,
                    evidence=[Evidence(quote=q) for q in quotes],
                )
            )

        graded = GradingResult(
            essay_id=essay.essay_id,
            scores=scores,
            prompt_version=self._prompt.id,
            model_name=result.model,
        )

        if self._check_grounding:
            fabricated = ungrounded_evidence(graded, essay.text)
            if fabricated:
                dims = sorted({d.value for d, _ in fabricated})
                return graded.model_copy(
                    update={
                        "needs_human_review": True,
                        "review_reason": (
                            f"원문에 없는 인용 {len(fabricated)}건 (항목: {', '.join(dims)})"
                        ),
                    }
                )
        return graded
