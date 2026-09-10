"""스키마가 실제로 나쁜 출력을 막는지 검증한다.

스키마 테스트의 요점은 '유효한 값이 통과하는가'가 아니라
'무효한 값이 확실히 거부되는가'다. LLM은 무효한 값을 만들어낸다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rubriq.schemas import (
    ALL_DIMENSIONS,
    DimensionScore,
    Essay,
    Evidence,
    GradingResult,
    GrammarError,
    RubricDimension,
    ungrounded_evidence,
)
from tests.conftest import SAMPLE_TEXT, make_result


class TestEssay:
    def test_word_count(self, sample_essay: Essay) -> None:
        assert sample_essay.word_count == len(SAMPLE_TEXT.split())

    def test_empty_text_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Essay(essay_id="x", text="")

    def test_whitespace_only_text_rejected(self) -> None:
        with pytest.raises(ValidationError, match="blank"):
            Essay(essay_id="x", text="   \n\t  ")

    def test_is_frozen(self, sample_essay: Essay) -> None:
        with pytest.raises(ValidationError):
            sample_essay.text = "mutated"  # type: ignore[misc]


class TestEvidence:
    def test_quote_only_is_valid(self) -> None:
        assert Evidence(quote="hello").start is None

    def test_empty_quote_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Evidence(quote="")

    def test_partial_offsets_rejected(self) -> None:
        with pytest.raises(ValidationError, match="together"):
            Evidence(quote="hello", start=0)

    def test_inverted_span_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be >"):
            Evidence(quote="hello", start=10, end=5)

    def test_span_length_must_match_quote(self) -> None:
        """LLM이 뱉은 offset이 인용문 길이와 안 맞으면 둘 중 하나는 거짓이다."""
        with pytest.raises(ValidationError, match="length"):
            Evidence(quote="hello", start=0, end=99)

    def test_matching_span_accepted(self) -> None:
        assert Evidence(quote="hello", start=3, end=8).end == 8


class TestDimensionScore:
    def test_score_below_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension=RubricDimension.GRAMMAR,
                score=0,
                rationale="r",
                evidence=[Evidence(quote="q")],
            )

    def test_score_above_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension=RubricDimension.GRAMMAR,
                score=6,
                rationale="r",
                evidence=[Evidence(quote="q")],
            )

    def test_score_without_evidence_rejected(self) -> None:
        """설계 문서 §1 '근거 인용 강제'가 스키마 레벨에서 지켜지는지."""
        with pytest.raises(ValidationError):
            DimensionScore(dimension=RubricDimension.GRAMMAR, score=3, rationale="r", evidence=[])

    def test_empty_rationale_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DimensionScore(
                dimension=RubricDimension.GRAMMAR,
                score=3,
                rationale="",
                evidence=[Evidence(quote="q")],
            )


class TestGradingResult:
    def test_valid_result(self, valid_result: GradingResult) -> None:
        assert len(valid_result.scores) == 6
        assert valid_result.score_of(RubricDimension.GRAMMAR) == 3

    def test_score_map_covers_all_dimensions(self, valid_result: GradingResult) -> None:
        assert set(valid_result.score_map()) == set(ALL_DIMENSIONS)

    def test_missing_dimension_rejected(self) -> None:
        """LLM이 항목 하나를 빠뜨리고 5개만 채점하는 흔한 실패."""
        scores = [
            DimensionScore(dimension=d, score=3, rationale="r", evidence=[Evidence(quote="q")])
            for d in ALL_DIMENSIONS
            if d is not RubricDimension.CONVENTIONS
        ]
        with pytest.raises(ValidationError, match="conventions"):
            GradingResult(essay_id="e", scores=scores)

    def test_duplicate_dimension_rejected(self) -> None:
        scores = [
            DimensionScore(dimension=d, score=3, rationale="r", evidence=[Evidence(quote="q")])
            for d in ALL_DIMENSIONS
        ]
        scores.append(scores[0])
        with pytest.raises(ValidationError, match="duplicate"):
            GradingResult(essay_id="e", scores=scores)

    def test_human_review_requires_reason(self) -> None:
        """이유 없이 사람에게 넘기면 넘겨받은 사람이 할 수 있는 게 없다."""
        with pytest.raises(ValidationError, match="review_reason"):
            make_result("e", dict.fromkeys(ALL_DIMENSIONS, 3), needs_human_review=True)

    def test_human_review_with_reason_accepted(self) -> None:
        result = make_result(
            "e",
            dict.fromkeys(ALL_DIMENSIONS, 3),
            needs_human_review=True,
            review_reason="grammar/conventions 점수 모순",
        )
        assert result.needs_human_review

    def test_negative_regrade_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GradingResult(
                essay_id="e",
                scores=[
                    DimensionScore(
                        dimension=d, score=3, rationale="r", evidence=[Evidence(quote="q")]
                    )
                    for d in ALL_DIMENSIONS
                ],
                regrade_count=-1,
            )


class TestGrounding:
    def test_quote_from_essay_is_grounded(self, sample_essay: Essay) -> None:
        result = make_result(
            sample_essay.essay_id,
            dict.fromkeys(ALL_DIMENSIONS, 3),
            quote="The hardest part was not vocabulary but confidence.",
        )
        assert ungrounded_evidence(result, sample_essay.text) == []

    def test_fabricated_quote_is_caught(self, sample_essay: Essay) -> None:
        """할루시네이션된 근거 탐지. 이게 이 함수의 존재 이유다."""
        result = make_result(
            sample_essay.essay_id,
            dict.fromkeys(ALL_DIMENSIONS, 3),
            quote="I have never written a single sentence in English.",
        )
        bad = ungrounded_evidence(result, sample_essay.text)
        assert len(bad) == 6  # 6개 항목 전부가 같은 가짜 인용을 씀
        assert bad[0][0] in ALL_DIMENSIONS

    def test_whitespace_differences_are_tolerated(self, sample_essay: Essay) -> None:
        """줄바꿈·중복 공백 차이로 오탐이 나면 검사 자체를 못 믿게 된다."""
        result = make_result(
            sample_essay.essay_id,
            dict.fromkeys(ALL_DIMENSIONS, 3),
            quote="The hardest part\n  was not   vocabulary but confidence.",
        )
        assert ungrounded_evidence(result, sample_essay.text) == []


class TestGrammarError:
    def test_valid(self) -> None:
        err = GrammarError(start=0, end=5, rule_id="UPPERCASE_SENTENCE_START", message="m")
        assert err.end > err.start

    def test_inverted_span_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GrammarError(start=10, end=3, rule_id="X", message="m")

    def test_zero_length_span_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GrammarError(start=5, end=5, rule_id="X", message="m")
