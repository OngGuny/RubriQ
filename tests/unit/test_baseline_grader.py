"""베이스라인 채점기 검증. LLM은 FakeLLM으로 대체해 결정적으로 돌린다.

여기서 확인하는 것은 채점 품질이 아니라 **배선**이다 —
LLM이 이상한 걸 뱉었을 때 조용히 통과시키지 않는가.
"""

from __future__ import annotations

import pytest

from rubriq.baseline.single_prompt import GradingError, SinglePromptGrader
from rubriq.llm.base import TokenUsage
from rubriq.prompts.registry import load_prompt
from rubriq.schemas import ALL_DIMENSIONS, Essay, RubricDimension
from tests.conftest import FakeLLM, make_llm_output

ESSAY_QUOTE = "The hardest part was not vocabulary but confidence."


class TestHappyPath:
    def test_produces_valid_result(self, sample_essay: Essay) -> None:
        llm = FakeLLM(make_llm_output(quote=ESSAY_QUOTE))
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert result.essay_id == sample_essay.essay_id
        assert len(result.scores) == 6
        assert not result.needs_human_review

    def test_records_prompt_version_and_model(self, sample_essay: Essay) -> None:
        """어떤 프롬프트·모델로 나온 숫자인지 결과에 남아야 재현이 된다."""
        llm = FakeLLM(make_llm_output(quote=ESSAY_QUOTE), model="claude-sonnet-5")
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert result.prompt_version == "scoring@v1"
        assert result.model_name == "claude-sonnet-5"

    def test_scores_are_carried_through(self, sample_essay: Essay) -> None:
        wanted = {d: i % 5 + 1 for i, d in enumerate(ALL_DIMENSIONS)}
        llm = FakeLLM(make_llm_output(wanted, quote=ESSAY_QUOTE))
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert result.score_map() == wanted

    def test_usage_is_exposed_for_cost_accounting(self, sample_essay: Essay) -> None:
        llm = FakeLLM(
            make_llm_output(quote=ESSAY_QUOTE),
            usage=TokenUsage(input_tokens=2000, output_tokens=600, cache_read_tokens=900),
        )
        grader = SinglePromptGrader(llm)
        grader.grade(sample_essay)
        assert grader.last_result is not None
        assert grader.last_result.usage.cache_hit
        assert grader.last_result.cost_usd > 0


class TestPromptWiring:
    def test_essay_goes_into_user_block_not_system(self, sample_essay: Essay) -> None:
        """**캐시 무효화 방지의 핵심 테스트.** 에세이가 캐시 프리픽스에 새면 안 된다."""
        llm = FakeLLM(make_llm_output(quote=ESSAY_QUOTE))
        SinglePromptGrader(llm).grade(sample_essay)
        call = llm.calls[0]
        assert sample_essay.text in call["user"]
        assert sample_essay.text not in call["system"]

    def test_system_block_identical_across_essays(self) -> None:
        """에세이가 달라도 캐시 대상은 바이트 단위로 같아야 한다."""
        llm = FakeLLM(make_llm_output(quote="a"))
        grader = SinglePromptGrader(llm, check_grounding=False)
        grader.grade(Essay(essay_id="1", text="first essay text"))
        grader.grade(Essay(essay_id="2", text="a totally different second essay"))
        assert llm.calls[0]["system"] == llm.calls[1]["system"]

    def test_uses_configured_prompt(self, sample_essay: Essay) -> None:
        llm = FakeLLM(make_llm_output(quote=ESSAY_QUOTE))
        grader = SinglePromptGrader(llm, prompt=load_prompt("scoring", "v1"))
        assert grader.prompt_id == "scoring@v1"


class TestMalformedLLMOutput:
    """LLM이 계약을 어겼을 때 조용히 넘어가지 않는가."""

    def test_missing_dimension_raises(self, sample_essay: Essay) -> None:
        llm = FakeLLM(make_llm_output(quote=ESSAY_QUOTE, omit=RubricDimension.CONVENTIONS))
        with pytest.raises(GradingError, match="conventions"):
            SinglePromptGrader(llm).grade(sample_essay)

    def test_score_above_range_raises(self, sample_essay: Essay) -> None:
        scores = dict.fromkeys(ALL_DIMENSIONS, 3) | {RubricDimension.GRAMMAR: 7}
        llm = FakeLLM(make_llm_output(scores, quote=ESSAY_QUOTE))
        with pytest.raises(GradingError, match="범위 밖"):
            SinglePromptGrader(llm).grade(sample_essay)

    def test_score_below_range_raises(self, sample_essay: Essay) -> None:
        scores = dict.fromkeys(ALL_DIMENSIONS, 3) | {RubricDimension.SYNTAX: 0}
        llm = FakeLLM(make_llm_output(scores, quote=ESSAY_QUOTE))
        with pytest.raises(GradingError, match="범위 밖"):
            SinglePromptGrader(llm).grade(sample_essay)

    def test_empty_evidence_raises(self, sample_essay: Essay) -> None:
        """근거 없는 점수는 받지 않는다 (설계 문서 §1 '근거 인용 강제')."""
        llm = FakeLLM(
            make_llm_output(quote=ESSAY_QUOTE, quotes_override={RubricDimension.GRAMMAR: []})
        )
        with pytest.raises(GradingError, match="근거 인용이 없다"):
            SinglePromptGrader(llm).grade(sample_essay)

    def test_whitespace_only_evidence_raises(self, sample_essay: Essay) -> None:
        llm = FakeLLM(
            make_llm_output(
                quote=ESSAY_QUOTE, quotes_override={RubricDimension.GRAMMAR: ["   ", "\n"]}
            )
        )
        with pytest.raises(GradingError, match="근거 인용이 없다"):
            SinglePromptGrader(llm).grade(sample_essay)


class TestGroundingCheck:
    def test_fabricated_quote_flags_human_review(self, sample_essay: Essay) -> None:
        """할루시네이션된 근거를 잡아 사람에게 넘긴다."""
        llm = FakeLLM(make_llm_output(quote="I have never written English before."))
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert result.needs_human_review
        assert result.review_reason and "원문에 없는 인용" in result.review_reason

    def test_scores_survive_grounding_failure(self, sample_essay: Essay) -> None:
        """근거가 부실해도 점수는 버리지 않는다. 그 판단은 사람이 한다."""
        wanted = {d: i % 5 + 1 for i, d in enumerate(ALL_DIMENSIONS)}
        llm = FakeLLM(make_llm_output(wanted, quote="fabricated text not in essay"))
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert result.score_map() == wanted
        assert result.needs_human_review

    def test_review_reason_names_dimensions(self, sample_essay: Essay) -> None:
        llm = FakeLLM(make_llm_output(quote="fabricated"))
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert result.review_reason is not None
        assert "grammar" in result.review_reason

    def test_grounding_check_can_be_disabled(self, sample_essay: Essay) -> None:
        llm = FakeLLM(make_llm_output(quote="fabricated text not in essay"))
        result = SinglePromptGrader(llm, check_grounding=False).grade(sample_essay)
        assert not result.needs_human_review

    def test_whitespace_normalised_quote_is_grounded(self, sample_essay: Essay) -> None:
        """줄바꿈 차이로 오탐이 나면 검사 자체를 못 믿는다."""
        llm = FakeLLM(make_llm_output(quote="The hardest part\n  was not   vocabulary"))
        result = SinglePromptGrader(llm).grade(sample_essay)
        assert not result.needs_human_review


class TestHarnessIntegration:
    def test_works_as_grader_in_evaluate(self, golden_items) -> None:  # noqa: ANN001
        """`Grader` 프로토콜을 실제로 만족하는지 평가 하네스에 물려 확인한다."""
        from eval.harness import evaluate

        llm = FakeLLM(make_llm_output())
        grader = SinglePromptGrader(llm, check_grounding=False)
        report = evaluate(grader, golden_items)
        assert report.n_items == len(golden_items)
        assert len(report.per_dimension) == 6
