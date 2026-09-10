"""평가 하네스 + 회귀 게이트 검증.

**이 파일이 이 스위트에서 가장 중요하다.**
"게이트가 통과한다"를 확인하는 건 검증이 아니다. 성능이 떨어졌을 때 **실제로 fail 하는지**를
확인해야 게이트를 믿을 수 있다. 아래 test_gate_fails_* 들이 그 역할을 한다.
모델이나 프롬프트를 바꿔 성능이 떨어졌을 때 CI가 실제로 빨간불이 되는지를 여기서 보장한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.harness import (
    GoldenItem,
    check_regression,
    evaluate,
    format_violations,
    load_golden_set,
)
from rubriq.schemas import ALL_DIMENSIONS
from tests.conftest import ConstantGrader, FakeGrader, build_golden_items


class TestLoadGoldenSet:
    def test_roundtrip(self, golden_jsonl: Path, golden_items: list[GoldenItem]) -> None:
        loaded = load_golden_set(golden_jsonl)
        assert len(loaded) == len(golden_items)
        assert loaded[0].essay.essay_id == golden_items[0].essay.essay_id
        assert loaded[0].gold_scores == golden_items[0].gold_scores

    def test_blank_lines_ignored(self, tmp_path: Path, golden_jsonl: Path) -> None:
        padded = tmp_path / "padded.jsonl"
        padded.write_text(
            "\n" + golden_jsonl.read_text(encoding="utf-8") + "\n\n", encoding="utf-8"
        )
        assert len(load_golden_set(padded)) == len(load_golden_set(golden_jsonl))

    def test_missing_dimension_reported_with_line_number(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text(
            json.dumps({"essay_id": "x", "text": "hello", "scores": {"cohesion": 3}}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=r"bad\.jsonl:1 missing gold scores"):
            load_golden_set(path)

    def test_invalid_json_reported_with_line_number(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"essay_id": "x"\n', encoding="utf-8")
        with pytest.raises(ValueError, match=r"bad\.jsonl:1 invalid JSON"):
            load_golden_set(path)

    def test_empty_file_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="is empty"):
            load_golden_set(path)


class TestEvaluate:
    def test_perfect_grader_scores_one(self, golden_items: list[GoldenItem]) -> None:
        report = evaluate(FakeGrader(golden_items, offset=0), golden_items)
        assert report.n_items == len(golden_items)
        assert report.mean_qwk == pytest.approx(1.0)
        assert all(d.exact_accuracy == 1.0 for d in report.per_dimension)

    def test_all_six_dimensions_reported(self, golden_items: list[GoldenItem]) -> None:
        report = evaluate(FakeGrader(golden_items), golden_items)
        assert {d.dimension for d in report.per_dimension} == set(ALL_DIMENSIONS)

    def test_worse_grader_scores_lower(self, golden_items: list[GoldenItem]) -> None:
        good = evaluate(FakeGrader(golden_items, offset=1), golden_items)
        bad = evaluate(FakeGrader(golden_items, offset=3), golden_items)
        assert good.mean_qwk is not None and bad.mean_qwk is not None
        assert good.mean_qwk > bad.mean_qwk

    def test_grading_failures_are_collected_not_raised(
        self, golden_items: list[GoldenItem]
    ) -> None:
        """한 건 실패로 50건 배치가 죽으면 매번 처음부터 다시 돌려야 한다."""
        failing = [golden_items[0].essay.essay_id, golden_items[1].essay.essay_id]
        report = evaluate(FakeGrader(golden_items, fail_ids=failing), golden_items)
        assert report.n_items == len(golden_items) - 2
        assert len(report.failures) == 2
        assert failing[0] in report.failures[0]

    def test_total_failure_raises(self, golden_items: list[GoldenItem]) -> None:
        all_ids = [i.essay.essay_id for i in golden_items]
        with pytest.raises(RuntimeError, match="모든 항목 채점 실패"):
            evaluate(FakeGrader(golden_items, fail_ids=all_ids), golden_items)

    def test_human_review_rate(self, golden_items: list[GoldenItem]) -> None:
        flagged = [i.essay.essay_id for i in golden_items[:3]]
        report = evaluate(FakeGrader(golden_items, needs_review_ids=flagged), golden_items)
        assert report.needs_human_review_rate == pytest.approx(3 / len(golden_items))

    def test_latency_is_measured(self, golden_items: list[GoldenItem]) -> None:
        report = evaluate(FakeGrader(golden_items), golden_items)
        assert report.latency.n == len(golden_items)
        assert report.latency.p95 >= report.latency.p50 >= 0

    def test_constant_grader_yields_unmeasurable_or_zero_qwk(
        self, golden_items: list[GoldenItem]
    ) -> None:
        """상수 채점기는 절대 좋은 점수를 받으면 안 된다."""
        report = evaluate(ConstantGrader(3), golden_items)
        for d in report.per_dimension:
            assert d.qwk is None or d.qwk == pytest.approx(0.0)

    def test_unmeasurable_dimension_is_none_not_zero(self) -> None:
        """측정 불가를 0.0으로 위장하면 '나쁜 성능'과 구별이 안 된다."""
        items = build_golden_items(n=5)
        flat = [
            GoldenItem(essay=i.essay, gold_scores=dict.fromkeys(ALL_DIMENSIONS, 3)) for i in items
        ]
        report = evaluate(ConstantGrader(3), flat)
        assert all(d.qwk is None for d in report.per_dimension)
        assert all(d.qwk_error for d in report.per_dimension)
        assert report.mean_qwk is None

    def test_report_serializes(self, golden_items: list[GoldenItem], tmp_path: Path) -> None:
        report = evaluate(
            FakeGrader(golden_items), golden_items, metadata={"model": "test", "prompt": "v1"}
        )
        out = report.write_json(tmp_path / "reports" / "r.json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["metadata"]["model"] == "test"
        assert len(data["per_dimension"]) == 6
        assert data["latency_ms"]["p95"] >= 0


class TestRegressionGate:
    """게이트가 침묵하지 않는지 확인하는 구간."""

    def test_gate_passes_for_good_grader(self, golden_items: list[GoldenItem]) -> None:
        report = evaluate(FakeGrader(golden_items, offset=0), golden_items)
        assert check_regression(report, qwk_threshold=0.60) == []

    def test_gate_fails_when_quality_drops(self, golden_items: list[GoldenItem]) -> None:
        """**핵심 테스트.** 채점기를 망가뜨리면 게이트가 반드시 잡아야 한다."""
        report = evaluate(FakeGrader(golden_items, offset=3), golden_items)
        violations = check_regression(report, qwk_threshold=0.60)
        assert violations, "성능이 무너졌는데 게이트가 통과했다"
        assert any("QWK" in v for v in violations)

    def test_gate_names_the_broken_dimension(self, golden_items: list[GoldenItem]) -> None:
        """총점만 보면 어느 축이 무너졌는지 모른다 (질문세트 Q8)."""
        report = evaluate(FakeGrader(golden_items, offset=3), golden_items)
        violations = check_regression(report, qwk_threshold=0.60)
        named = {d.value for d in ALL_DIMENSIONS if any(d.value in v for v in violations)}
        assert named, "위반 메시지에 항목 이름이 없다"

    def test_gate_fails_on_unmeasurable_dimension(self) -> None:
        """QWK가 nan이라 측정 불가인 상태가 조용히 통과하면 안 된다."""
        items = build_golden_items(n=5)
        flat = [
            GoldenItem(essay=i.essay, gold_scores=dict.fromkeys(ALL_DIMENSIONS, 3)) for i in items
        ]
        report = evaluate(ConstantGrader(3), flat)
        violations = check_regression(report, qwk_threshold=0.60)
        assert any("측정 불가" in v for v in violations)

    def test_gate_fails_on_grading_failures(self, golden_items: list[GoldenItem]) -> None:
        report = evaluate(
            FakeGrader(golden_items, offset=0, fail_ids=[golden_items[0].essay.essay_id]),
            golden_items,
        )
        violations = check_regression(report, qwk_threshold=0.60)
        assert any("실패율" in v for v in violations)

    def test_failure_rate_tolerance_can_be_relaxed(self, golden_items: list[GoldenItem]) -> None:
        report = evaluate(
            FakeGrader(golden_items, offset=0, fail_ids=[golden_items[0].essay.essay_id]),
            golden_items,
        )
        assert check_regression(report, 0.60, max_failure_rate=0.10) == []

    def test_threshold_boundary_is_inclusive(self, golden_items: list[GoldenItem]) -> None:
        """임계치와 정확히 같으면 통과한다 (>= 기준)."""
        report = evaluate(FakeGrader(golden_items, offset=0), golden_items)
        assert report.mean_qwk == pytest.approx(1.0)
        assert check_regression(report, qwk_threshold=1.0) == []

    def test_gate_collects_all_violations_at_once(self, golden_items: list[GoldenItem]) -> None:
        """CI 한 번에 무너진 곳을 다 보여줘야 한다. 하나씩 고치며 재실행하면 느리다."""
        report = evaluate(
            FakeGrader(golden_items, offset=4, fail_ids=[golden_items[0].essay.essay_id]),
            golden_items,
        )
        violations = check_regression(report, qwk_threshold=0.60)
        assert len(violations) > 2
        assert any("실패율" in v for v in violations)

    def test_format_violations_is_readable(self) -> None:
        text = format_violations(["[grammar] QWK 0.1 < 임계치 0.6"])
        assert "회귀 감지" in text
        assert "grammar" in text
