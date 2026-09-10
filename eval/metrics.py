"""평가 지표. 설계 문서 §3의 지표들을 여기서 계산한다.

설계 메모 — sklearn 동작을 직접 확인한 결과:
- `cohen_kappa_score(weights="quadratic")`는 **정답과 예측이 모두 같은 값 하나로 상수면 nan**을
  돌려준다. `nan >= threshold`는 False라 assert는 통과하지 않지만, 부호를 뒤집어 쓴 조건
  (`not (qwk < threshold)`)에서는 조용히 통과한다. 그래서 여기서 nan을 명시적으로 잡아
  DegenerateGoldenSet로 올린다. 회귀 게이트가 침묵하는 것이 게이트가 없는 것보다 나쁘다.
- quadratic weight는 사용되지 않는 라벨을 추가해도 값이 변하지 않는다(분자·분모가 같은 배율).
  그래도 `labels`를 넘기는 이유는 값 보정이 아니라 **범위 밖 점수를 조기에 잡기 위해서**다.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.metrics import cohen_kappa_score

DEFAULT_LABELS: tuple[int, ...] = (1, 2, 3, 4, 5)


class DegenerateGoldenSet(ValueError):
    """QWK를 정의할 수 없는 골든셋. 지표가 아니라 데이터 문제다."""


def _check_pair(y_true: Sequence[int], y_pred: Sequence[int], labels: Sequence[int]) -> None:
    if len(y_true) != len(y_pred):
        raise ValueError(f"length mismatch: {len(y_true)} vs {len(y_pred)}")
    if not y_true:
        raise ValueError("empty input")
    allowed = set(labels)
    for name, seq in (("y_true", y_true), ("y_pred", y_pred)):
        bad = sorted({v for v in seq if v not in allowed})
        if bad:
            raise ValueError(f"{name} has values outside {sorted(allowed)}: {bad}")


def quadratic_weighted_kappa(
    y_true: Sequence[int],
    y_pred: Sequence[int],
    labels: Sequence[int] = DEFAULT_LABELS,
) -> float:
    """인간 채점 대비 일치도. 순서형 점수의 표준 지표.

    Raises:
        DegenerateGoldenSet: 정답이 단일 값이라 분산이 없어 QWK가 정의되지 않을 때.
    """
    _check_pair(y_true, y_pred, labels)
    if len(set(y_true)) == 1 and len(set(y_pred)) == 1:
        raise DegenerateGoldenSet(
            "y_true와 y_pred가 모두 상수라 QWK가 정의되지 않는다 "
            f"(y_true={y_true[0]}, y_pred={y_pred[0]}). 골든셋에 점수 분산이 필요하다."
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value = float(cohen_kappa_score(y_true, y_pred, weights="quadratic", labels=list(labels)))
    if math.isnan(value):
        raise DegenerateGoldenSet(f"QWK is nan for y_true={list(y_true)}, y_pred={list(y_pred)}")
    return value


def exact_accuracy(y_true: Sequence[int], y_pred: Sequence[int]) -> float:
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("invalid input")
    return sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(y_true)


def adjacent_accuracy(y_true: Sequence[int], y_pred: Sequence[int], tolerance: int = 1) -> float:
    """|예측 - 정답| <= tolerance 비율. 1점 차이는 교사도 갈린다는 실무 수용 기준."""
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("invalid input")
    return sum(abs(t - p) <= tolerance for t, p in zip(y_true, y_pred, strict=True)) / len(y_true)


def consistency_sigma(repeats: Sequence[Sequence[float]]) -> float:
    """동일 입력 반복 채점의 표준편차 평균. 낮을수록 일관적.

    Args:
        repeats: 에세이(또는 항목)별 반복 점수 그룹. 각 그룹은 2회 이상이어야 한다.

    temperature 0에서도 0이 되지 않는다. 이 값이 JD가 말하는 '일관성' 개선의 대상이다.
    """
    if not repeats:
        raise ValueError("empty input")
    sigmas: list[float] = []
    for i, group in enumerate(repeats):
        if len(group) < 2:
            raise ValueError(f"group {i} has {len(group)} sample(s); need >= 2")
        sigmas.append(float(np.std(group, ddof=1)))  # 표본 표준편차
    return float(np.mean(sigmas))


@dataclass(frozen=True, slots=True)
class PRF:
    precision: float
    recall: float
    f1: float
    true_positives: int
    n_predicted: int
    n_gold: int

    def f_beta(self, beta: float) -> float:
        """beta<1이면 precision 가중. 교육 도메인에서 오탐이 미탐보다 비싸므로 beta=0.5를 본다."""
        if self.precision == 0.0 and self.recall == 0.0:
            return 0.0
        b2 = beta * beta
        return (1 + b2) * self.precision * self.recall / (b2 * self.precision + self.recall)


def spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """[start, end) 두 구간이 한 글자라도 겹치는가."""
    return a[0] < b[1] and b[0] < a[1]


def detection_prf[T, G](
    predicted: Sequence[T],
    gold: Sequence[G],
    match: Callable[[T, G], bool],
) -> PRF:
    """오류 탐지 P/R/F1. 한 예측이 여러 정답을 먹지 못하도록 1:1 그리디 매칭한다.

    관례: 예측·정답이 모두 비면 완벽(1.0)으로 본다. 예측만 비면 precision은 0.0으로 둔다.
    """
    if not predicted and not gold:
        return PRF(1.0, 1.0, 1.0, 0, 0, 0)

    unmatched_gold = list(range(len(gold)))
    tp = 0
    for p in predicted:
        for gi in unmatched_gold:
            if match(p, gold[gi]):
                tp += 1
                unmatched_gold.remove(gi)
                break

    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return PRF(precision, recall, f1, tp, len(predicted), len(gold))


@dataclass(frozen=True, slots=True)
class LatencyStats:
    p50: float
    p95: float
    mean: float
    n: int


def latency_stats(latencies_ms: Sequence[float]) -> LatencyStats:
    """p50이 아니라 p95를 본다. 꼬리 지연이 사용자가 체감하는 지연이다."""
    if not latencies_ms:
        raise ValueError("empty input")
    arr = np.asarray(latencies_ms, dtype=float)
    if np.any(arr < 0):
        raise ValueError("negative latency")
    return LatencyStats(
        p50=float(np.percentile(arr, 50)),
        p95=float(np.percentile(arr, 95)),
        mean=float(arr.mean()),
        n=len(arr),
    )
