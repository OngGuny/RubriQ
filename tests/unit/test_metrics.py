"""지표 계산 검증. 손으로 계산 가능한 값과 대조한다."""

from __future__ import annotations

import math

import pytest

from eval.metrics import (
    DegenerateGoldenSet,
    LatencyStats,
    adjacent_accuracy,
    consistency_sigma,
    detection_prf,
    exact_accuracy,
    latency_stats,
    quadratic_weighted_kappa,
    spans_overlap,
)


class TestQWK:
    def test_perfect_agreement_is_one(self) -> None:
        assert quadratic_weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)

    def test_total_disagreement_is_negative(self) -> None:
        assert quadratic_weighted_kappa([1, 1, 5, 5], [5, 5, 1, 1]) == pytest.approx(-1.0)

    def test_known_value(self) -> None:
        # 전 구간 1점씩 밀린 예측. sklearn 실측값과 고정 대조.
        assert quadratic_weighted_kappa([1, 2, 3, 4, 5], [2, 3, 4, 5, 4]) == pytest.approx(
            0.7058823529, rel=1e-9
        )

    def test_closer_predictions_score_higher(self) -> None:
        """순서형 지표의 핵심 성질: 1점 차이가 3점 차이보다 나아야 한다."""
        truth = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
        near = [2, 2, 3, 4, 4, 1, 3, 3, 4, 4]
        far = [4, 5, 1, 1, 2, 5, 5, 1, 1, 2]
        assert quadratic_weighted_kappa(truth, near) > quadratic_weighted_kappa(truth, far)

    def test_constant_both_sides_raises_instead_of_nan(self) -> None:
        """핵심 회귀 방어: nan을 그대로 흘리면 게이트가 조용히 통과할 수 있다."""
        with pytest.raises(DegenerateGoldenSet):
            quadratic_weighted_kappa([3, 3, 3, 3], [3, 3, 3, 3])

    def test_constant_prediction_against_varied_truth_is_zero(self) -> None:
        # 상수 예측기는 nan이 아니라 0.0. '아무것도 안 하는 채점기'의 점수가 0이어야 한다.
        assert quadratic_weighted_kappa([1, 2, 3, 4], [3, 3, 3, 3]) == pytest.approx(0.0)

    def test_never_returns_nan(self) -> None:
        value = quadratic_weighted_kappa([1, 2, 3], [1, 2, 3])
        assert not math.isnan(value)

    def test_rejects_out_of_range_scores(self) -> None:
        with pytest.raises(ValueError, match="outside"):
            quadratic_weighted_kappa([1, 2, 3], [1, 2, 7])

    def test_rejects_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="length mismatch"):
            quadratic_weighted_kappa([1, 2, 3], [1, 2])

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            quadratic_weighted_kappa([], [])


class TestAccuracy:
    def test_exact_accuracy(self) -> None:
        assert exact_accuracy([1, 2, 3, 4], [1, 2, 3, 5]) == pytest.approx(0.75)

    def test_adjacent_tolerates_one_point(self) -> None:
        assert adjacent_accuracy([1, 2, 3, 4], [2, 3, 4, 5]) == pytest.approx(1.0)

    def test_adjacent_rejects_two_point_gap(self) -> None:
        assert adjacent_accuracy([1, 2, 3, 4], [3, 2, 3, 4]) == pytest.approx(0.75)

    def test_adjacent_is_at_least_exact(self) -> None:
        truth, pred = [1, 3, 5, 2, 4], [2, 3, 4, 4, 4]
        assert adjacent_accuracy(truth, pred) >= exact_accuracy(truth, pred)

    def test_zero_tolerance_equals_exact(self) -> None:
        truth, pred = [1, 3, 5, 2, 4], [2, 3, 4, 4, 4]
        assert adjacent_accuracy(truth, pred, tolerance=0) == exact_accuracy(truth, pred)

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValueError):
            adjacent_accuracy([1], [1], tolerance=-1)


class TestConsistencySigma:
    def test_identical_repeats_give_zero(self) -> None:
        assert consistency_sigma([[3, 3, 3], [4, 4, 4]]) == pytest.approx(0.0)

    def test_known_sample_stdev(self) -> None:
        # [2,4]의 표본 표준편차 = sqrt(((2-3)^2+(4-3)^2)/1) = sqrt(2)
        assert consistency_sigma([[2, 4]]) == pytest.approx(math.sqrt(2))

    def test_averages_across_groups(self) -> None:
        assert consistency_sigma([[2, 4], [3, 3]]) == pytest.approx(math.sqrt(2) / 2)

    def test_single_sample_group_rejected(self) -> None:
        """1회만 돌리고 '일관성 측정했다'고 하지 못하게 막는다."""
        with pytest.raises(ValueError, match="need >= 2"):
            consistency_sigma([[3]])

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            consistency_sigma([])


class TestDetectionPRF:
    @staticmethod
    def _match(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return spans_overlap(a, b)

    def test_perfect_detection(self) -> None:
        spans = [(0, 5), (10, 15)]
        prf = detection_prf(spans, spans, self._match)
        assert (prf.precision, prf.recall, prf.f1) == (1.0, 1.0, 1.0)

    def test_false_positive_lowers_precision_only(self) -> None:
        prf = detection_prf([(0, 5), (100, 105)], [(0, 5)], self._match)
        assert prf.precision == pytest.approx(0.5)
        assert prf.recall == pytest.approx(1.0)

    def test_missed_error_lowers_recall_only(self) -> None:
        prf = detection_prf([(0, 5)], [(0, 5), (10, 15)], self._match)
        assert prf.precision == pytest.approx(1.0)
        assert prf.recall == pytest.approx(0.5)

    def test_one_prediction_cannot_match_two_gold(self) -> None:
        """1:1 매칭 강제. 넓은 스팬 하나로 모든 정답을 먹으면 recall이 부풀려진다."""
        prf = detection_prf([(0, 100)], [(0, 5), (10, 15)], self._match)
        assert prf.true_positives == 1
        assert prf.recall == pytest.approx(0.5)

    def test_both_empty_is_perfect(self) -> None:
        prf = detection_prf([], [], self._match)
        assert prf.f1 == pytest.approx(1.0)

    def test_no_predictions_with_gold_scores_zero(self) -> None:
        prf = detection_prf([], [(0, 5)], self._match)
        assert (prf.precision, prf.recall, prf.f1) == (0.0, 0.0, 0.0)

    def test_f_beta_half_favors_precision(self) -> None:
        """교육 도메인 전제: 오탐이 미탐보다 비싸다."""
        high_precision = detection_prf([(0, 5)], [(0, 5), (10, 15)], self._match)  # P=1.0 R=0.5
        high_recall = detection_prf([(0, 5), (100, 105)], [(0, 5)], self._match)  # P=0.5 R=1.0
        assert high_precision.f1 == pytest.approx(high_recall.f1)  # F1은 동점
        assert high_precision.f_beta(0.5) > high_recall.f_beta(0.5)  # F0.5는 갈린다

    def test_f_beta_zero_when_no_matches(self) -> None:
        prf = detection_prf([(0, 5)], [(50, 55)], self._match)
        assert prf.f_beta(0.5) == 0.0


class TestSpansOverlap:
    def test_overlapping(self) -> None:
        assert spans_overlap((0, 10), (5, 15))

    def test_touching_is_not_overlap(self) -> None:
        # [start, end) 반열림 구간이므로 (0,5)와 (5,10)은 겹치지 않는다.
        assert not spans_overlap((0, 5), (5, 10))

    def test_disjoint(self) -> None:
        assert not spans_overlap((0, 5), (10, 15))


class TestLatency:
    def test_percentiles(self) -> None:
        stats = latency_stats([float(x) for x in range(1, 101)])
        assert isinstance(stats, LatencyStats)
        assert stats.p50 == pytest.approx(50.5)
        assert stats.p95 == pytest.approx(95.05)
        assert stats.n == 100

    def test_p95_tracks_tail_not_median(self) -> None:
        """꼬리 지연 방어가 되는지: 이상치 하나가 p50은 안 흔들고 p95만 올려야 한다."""
        base = [100.0] * 19 + [100.0]
        tail = [100.0] * 19 + [5000.0]
        assert latency_stats(base).p50 == latency_stats(tail).p50
        assert latency_stats(tail).p95 > latency_stats(base).p95

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            latency_stats([])

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            latency_stats([10.0, -1.0])
