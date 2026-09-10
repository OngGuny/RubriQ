"""공용 fixture.

여기 있는 가짜 채점기(FakeGrader)들이 이 테스트 스위트의 핵심 장치다.
LLM 없이 평가 하네스와 회귀 게이트의 동작을 결정적으로 검증한다.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path

import pytest

from eval.harness import GoldenItem
from rubriq.baseline.single_prompt import LLMDimensionScore, LLMGradingOutput
from rubriq.llm.base import LLMResult, TokenUsage
from rubriq.schemas import (
    ALL_DIMENSIONS,
    DimensionScore,
    Essay,
    Evidence,
    GradeLevel,
    GradingResult,
    RubricDimension,
)

SAMPLE_TEXT = (
    "Learning a second language is difficult but rewarding. "
    "When I started studying English, I could not order food at a restaurant. "
    "Now I can read novels and write essays like this one. "
    "The hardest part was not vocabulary but confidence."
)


@pytest.fixture
def sample_essay() -> Essay:
    return Essay(
        essay_id="e-001",
        text=SAMPLE_TEXT,
        grade_level=GradeLevel.MIDDLE,
        task_type="opinion",
    )


def make_result(
    essay_id: str,
    scores: dict[RubricDimension, int],
    *,
    quote: str = "Learning a second language is difficult but rewarding.",
    needs_human_review: bool = False,
    review_reason: str | None = None,
) -> GradingResult:
    """6개 항목이 모두 채워진 유효한 GradingResult를 만든다."""
    return GradingResult(
        essay_id=essay_id,
        scores=[
            DimensionScore(
                dimension=dim,
                score=scores[dim],
                rationale=f"{dim.value} rationale",
                evidence=[Evidence(quote=quote)],
            )
            for dim in ALL_DIMENSIONS
        ],
        needs_human_review=needs_human_review,
        review_reason=review_reason,
    )


@pytest.fixture
def valid_result(sample_essay: Essay) -> GradingResult:
    return make_result(sample_essay.essay_id, dict.fromkeys(ALL_DIMENSIONS, 3))


class FakeGrader:
    """골든 점수에 결정적인 오프셋을 더해 돌려주는 채점기.

    offset=0이면 완벽한 채점기, 크게 줄수록 나쁜 채점기.
    회귀 게이트가 '나빠졌을 때 실제로 fail 하는지'를 이걸로 확인한다.
    """

    def __init__(
        self,
        items: Sequence[GoldenItem],
        offset: int = 0,
        *,
        fail_ids: Sequence[str] = (),
        needs_review_ids: Sequence[str] = (),
    ) -> None:
        self._gold = {i.essay.essay_id: i.gold_scores for i in items}
        self._offset = offset
        self._fail_ids = set(fail_ids)
        self._review_ids = set(needs_review_ids)
        self.calls = 0

    def grade(self, essay: Essay) -> GradingResult:
        self.calls += 1
        if essay.essay_id in self._fail_ids:
            raise RuntimeError(f"simulated grading failure for {essay.essay_id}")
        gold = self._gold[essay.essay_id]
        shifted = {d: max(1, min(5, gold[d] + self._offset)) for d in ALL_DIMENSIONS}
        needs_review = essay.essay_id in self._review_ids
        return make_result(
            essay.essay_id,
            shifted,
            quote=essay.text[:40],
            needs_human_review=needs_review,
            review_reason="simulated disagreement" if needs_review else None,
        )


class ConstantGrader:
    """모든 에세이에 같은 점수를 주는 채점기. 퇴화 케이스 탐지용."""

    def __init__(self, score: int = 3) -> None:
        self._score = score

    def grade(self, essay: Essay) -> GradingResult:
        return make_result(
            essay.essay_id,
            dict.fromkeys(ALL_DIMENSIONS, self._score),
            quote=essay.text[:40],
        )


def build_golden_items(n: int = 12, seed: int = 7) -> list[GoldenItem]:
    """점수 분산이 있는 합성 골든셋. QWK가 정의되려면 분산이 필요하다."""
    rng = random.Random(seed)
    items: list[GoldenItem] = []
    for i in range(n):
        items.append(
            GoldenItem(
                essay=Essay(essay_id=f"g-{i:03d}", text=f"{SAMPLE_TEXT} (variant {i})"),
                # 항목마다 다른 점수가 나오도록 순환 + 약간의 노이즈
                gold_scores={
                    d: 1 + ((i + j) % 5) if rng.random() > 0.15 else 1 + (i % 5)
                    for j, d in enumerate(ALL_DIMENSIONS)
                },
            )
        )
    return items


@pytest.fixture
def golden_items() -> list[GoldenItem]:
    return build_golden_items()


@pytest.fixture
def golden_jsonl(tmp_path: Path, golden_items: list[GoldenItem]) -> Path:
    import json

    path = tmp_path / "golden.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for item in golden_items:
            f.write(
                json.dumps(
                    {
                        "essay_id": item.essay.essay_id,
                        "text": item.essay.text,
                        "scores": {d.value: s for d, s in item.gold_scores.items()},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


class FakeLLM:
    """LLM 호출 없이 미리 정한 구조화 출력을 돌려준다.

    `StructuredLLM` 프로토콜을 만족한다. 호출 인자를 기록해서
    "가변 내용이 캐시 프리픽스에 들어갔는지" 같은 것도 검증할 수 있다.
    """

    def __init__(
        self,
        output: LLMGradingOutput,
        *,
        model: str = "claude-opus-5",
        usage: TokenUsage | None = None,
    ) -> None:
        self._output = output
        self._model = model
        self._usage = usage or TokenUsage(input_tokens=1000, output_tokens=500)
        self.calls: list[dict[str, str]] = []

    def complete(self, *, cacheable_system, user_content, schema):  # noqa: ANN001, ANN201
        self.calls.append({"system": cacheable_system, "user": user_content})
        return LLMResult(
            output=self._output,
            model=self._model,
            usage=self._usage,
            latency_ms=12.5,
            raw_stop_reason="end_turn",
        )


def make_llm_output(
    scores: dict[RubricDimension, int] | None = None,
    *,
    quote: str = "Learning a second language is difficult but rewarding.",
    omit: RubricDimension | None = None,
    quotes_override: dict[RubricDimension, list[str]] | None = None,
) -> LLMGradingOutput:
    """LLM 원시 출력을 만든다. `omit`으로 항목 누락 같은 실패를 재현한다."""
    scores = scores or dict.fromkeys(ALL_DIMENSIONS, 3)
    quotes_override = quotes_override or {}
    items = [
        LLMDimensionScore(
            dimension=dim,
            score=scores[dim],
            evidence_quotes=quotes_override.get(dim, [quote]),
            rationale=f"{dim.value} looks like this",
        )
        for dim in ALL_DIMENSIONS
        if dim is not omit
    ]
    return LLMGradingOutput(scores=items)
