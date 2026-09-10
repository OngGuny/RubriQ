"""골든셋 러너 + 회귀 게이트.

게이트 로직(`check_regression`)은 LLM 없이 테스트 가능하도록 채점기와 분리돼 있다.
`tests/unit/test_harness.py`의 TestRegressionGate가 가짜 채점기로
'성능이 떨어지면 실제로 fail 하는가'를 검증한다.
게이트가 통과만 하는 걸 확인하는 건 검증이 아니다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eval.metrics import (
    DegenerateGoldenSet,
    LatencyStats,
    adjacent_accuracy,
    exact_accuracy,
    latency_stats,
    quadratic_weighted_kappa,
)
from rubriq.schemas import ALL_DIMENSIONS, Essay, GradeLevel, GradingResult, RubricDimension


@dataclass(frozen=True, slots=True)
class GoldenItem:
    """골든셋 한 건: 에세이 + 인간 채점 점수."""

    essay: Essay
    gold_scores: dict[RubricDimension, int]


class Grader(Protocol):
    """채점기 인터페이스. 베이스라인과 Agent가 같은 인터페이스를 구현해 비교 가능해진다."""

    def grade(self, essay: Essay) -> GradingResult: ...


def load_golden_set(path: str | Path) -> list[GoldenItem]:
    """jsonl 골든셋을 읽는다.

    한 줄 형식:
        {"essay_id": "...", "text": "...", "grade_level": "middle",
         "scores": {"cohesion": 3, "syntax": 4, ...}}
    """
    path = Path(path)
    items: list[GoldenItem] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno} invalid JSON: {e}") from e

            raw_scores = raw.get("scores") or {}
            missing = [d.value for d in ALL_DIMENSIONS if d.value not in raw_scores]
            if missing:
                raise ValueError(f"{path}:{lineno} missing gold scores: {missing}")

            grade_level = raw.get("grade_level")
            items.append(
                GoldenItem(
                    essay=Essay(
                        essay_id=raw["essay_id"],
                        text=raw["text"],
                        grade_level=GradeLevel(grade_level) if grade_level else None,
                        task_type=raw.get("task_type"),
                        prompt=raw.get("prompt"),
                    ),
                    gold_scores={d: int(raw_scores[d.value]) for d in ALL_DIMENSIONS},
                )
            )
    if not items:
        raise ValueError(f"{path} is empty")
    return items


@dataclass(frozen=True, slots=True)
class DimensionMetrics:
    dimension: RubricDimension
    qwk: float | None  # 항목별 분산이 없으면 None (측정 불가를 0.0으로 위장하지 않는다)
    qwk_error: str | None
    exact_accuracy: float
    adjacent_accuracy: float
    n: int


@dataclass(slots=True)
class EvaluationReport:
    n_items: int
    per_dimension: list[DimensionMetrics]
    latency: LatencyStats
    needs_human_review_rate: float
    failures: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def measurable_qwks(self) -> list[float]:
        return [d.qwk for d in self.per_dimension if d.qwk is not None]

    @property
    def mean_qwk(self) -> float | None:
        """항목별 QWK의 산술평균. 측정 가능한 항목이 하나도 없으면 None."""
        vals = self.measurable_qwks
        return sum(vals) / len(vals) if vals else None

    def to_dict(self) -> dict[str, object]:
        return {
            "n_items": self.n_items,
            "mean_qwk": self.mean_qwk,
            "per_dimension": [
                {
                    "dimension": d.dimension.value,
                    "qwk": d.qwk,
                    "qwk_error": d.qwk_error,
                    "exact_accuracy": d.exact_accuracy,
                    "adjacent_accuracy": d.adjacent_accuracy,
                    "n": d.n,
                }
                for d in self.per_dimension
            ],
            "latency_ms": {
                "p50": self.latency.p50,
                "p95": self.latency.p95,
                "mean": self.latency.mean,
                "n": self.latency.n,
            },
            "needs_human_review_rate": self.needs_human_review_rate,
            "failures": self.failures,
            "metadata": self.metadata,
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def evaluate(
    grader: Grader,
    items: Sequence[GoldenItem],
    metadata: dict[str, str] | None = None,
) -> EvaluationReport:
    """골든셋 전체를 채점하고 지표를 낸다.

    개별 에세이 채점 실패는 예외를 올리지 않고 `report.failures`에 모은다.
    한 건 때문에 전체 평가가 죽으면 50건짜리 배치를 매번 처음부터 다시 돌려야 한다.
    """
    predictions: dict[RubricDimension, list[int]] = {d: [] for d in ALL_DIMENSIONS}
    golds: dict[RubricDimension, list[int]] = {d: [] for d in ALL_DIMENSIONS}
    latencies: list[float] = []
    failures: list[str] = []
    review_flags = 0
    graded = 0

    for item in items:
        started = time.perf_counter()
        try:
            result = grader.grade(item.essay)
        except Exception as e:  # noqa: BLE001 - 개별 실패를 모아서 보고하는 것이 목적
            failures.append(f"{item.essay.essay_id}: {type(e).__name__}: {e}")
            continue
        latencies.append((time.perf_counter() - started) * 1000.0)
        graded += 1
        if result.needs_human_review:
            review_flags += 1
        predicted = result.score_map()
        for dim in ALL_DIMENSIONS:
            predictions[dim].append(predicted[dim])
            golds[dim].append(item.gold_scores[dim])

    if graded == 0:
        raise RuntimeError(f"모든 항목 채점 실패 ({len(items)}건). 첫 실패: {failures[0]}")

    per_dimension: list[DimensionMetrics] = []
    for dim in ALL_DIMENSIONS:
        y_true, y_pred = golds[dim], predictions[dim]
        qwk: float | None
        qwk_error: str | None = None
        try:
            qwk = quadratic_weighted_kappa(y_true, y_pred)
        except DegenerateGoldenSet as e:
            qwk, qwk_error = None, str(e)
        per_dimension.append(
            DimensionMetrics(
                dimension=dim,
                qwk=qwk,
                qwk_error=qwk_error,
                exact_accuracy=exact_accuracy(y_true, y_pred),
                adjacent_accuracy=adjacent_accuracy(y_true, y_pred),
                n=len(y_true),
            )
        )

    return EvaluationReport(
        n_items=graded,
        per_dimension=per_dimension,
        latency=latency_stats(latencies),
        needs_human_review_rate=review_flags / graded,
        failures=failures,
        metadata=metadata or {},
    )


def check_regression(
    report: EvaluationReport,
    qwk_threshold: float,
    *,
    max_failure_rate: float = 0.0,
    require_all_dimensions_measurable: bool = True,
) -> list[str]:
    """회귀 위반 목록. 빈 리스트면 통과.

    예외를 던지지 않고 목록으로 돌려주는 이유: 위반이 여러 개일 때 한 번에 다 보여줘야
    "어느 항목이 무너졌는지"를 한 번의 CI 실행으로 알 수 있다.
    """
    violations: list[str] = []

    if require_all_dimensions_measurable:
        for d in report.per_dimension:
            if d.qwk is None:
                violations.append(f"[{d.dimension.value}] QWK 측정 불가: {d.qwk_error}")

    for d in report.per_dimension:
        if d.qwk is not None and d.qwk < qwk_threshold:
            violations.append(f"[{d.dimension.value}] QWK {d.qwk:.4f} < 임계치 {qwk_threshold:.4f}")

    mean = report.mean_qwk
    if mean is None:
        violations.append("전체 QWK 측정 불가 (측정 가능한 항목 없음)")
    elif mean < qwk_threshold:
        violations.append(f"[전체] 평균 QWK {mean:.4f} < 임계치 {qwk_threshold:.4f}")

    attempted = report.n_items + len(report.failures)
    failure_rate = len(report.failures) / attempted if attempted else 0.0
    if failure_rate > max_failure_rate:
        violations.append(
            f"채점 실패율 {failure_rate:.1%} > 허용 {max_failure_rate:.1%} "
            f"({len(report.failures)}/{attempted}건)"
        )

    return violations


def format_violations(violations: Iterable[str]) -> str:
    return "회귀 감지:\n" + "\n".join(f"  - {v}" for v in violations)
