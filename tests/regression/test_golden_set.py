"""골든셋 회귀 테스트. **실제 LLM을 호출한다 — 유료·느림.**

기본 `pytest` 실행에서는 제외된다 (pyproject의 `addopts = -m 'not regression'`).
명시 실행:  uv run pytest -m regression

전제 조건이 없으면 fail이 아니라 skip 한다. 채점기가 아직 없는 단계에서 CI가 빨간불이면
빨간불의 의미가 희석되고, 결국 아무도 안 본다.

게이트 **로직** 자체는 `tests/unit/test_harness.py`에서 가짜 채점기로 검증한다.
이 파일은 실제 채점기를 그 로직에 물리는 배선만 담당한다.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval.harness import (
    Grader,
    check_regression,
    evaluate,
    format_violations,
    load_golden_set,
)
from rubriq.config import get_settings

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = Path(os.getenv("RUBRIQ_GOLDEN_SET", REPO_ROOT / "eval/golden/ellipse-50.jsonl"))
REPORT_DIR = REPO_ROOT / "eval/reports"


def _load_grader() -> Grader:
    """설정된 채점기를 만든다. 아직 구현 전이면 skip 사유를 명확히 남긴다."""
    try:
        from rubriq.baseline.single_prompt import SinglePromptGrader
    except ImportError as e:
        pytest.skip(f"채점기 미구현 (T0 진행 중): {e}")
    return SinglePromptGrader()


@pytest.fixture(scope="module")
def golden_items():
    if not GOLDEN_PATH.exists():
        pytest.skip(f"골든셋 없음: {GOLDEN_PATH} (scripts/build_golden_set.py 참조)")
    return load_golden_set(GOLDEN_PATH)


@pytest.fixture(scope="module")
def report(golden_items):
    settings = get_settings()
    if not (settings.openai_api_key or settings.anthropic_api_key):
        pytest.skip("LLM API 키 없음 (.env 참조)")

    grader = _load_grader()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = evaluate(
        grader,
        golden_items,
        metadata={
            "golden_set": GOLDEN_PATH.name,
            "n_items": str(len(golden_items)),
            "timestamp": stamp,
            "git_sha": os.getenv("GITHUB_SHA", "local"),
        },
    )
    # 결과는 통과 여부와 무관하게 항상 남긴다. fail 했을 때의 숫자가 가장 필요한 숫자다.
    result.write_json(REPORT_DIR / f"regression-{stamp}.json")
    return result


def test_qwk_above_threshold(report) -> None:
    """QWK가 임계치 아래로 떨어지면 빌드를 fail 시킨다."""
    threshold = get_settings().regression_qwk_threshold
    violations = check_regression(report, qwk_threshold=threshold)
    assert not violations, format_violations(violations)


def test_no_grading_failures(report) -> None:
    assert not report.failures, "채점 실패:\n" + "\n".join(f"  - {f}" for f in report.failures)


def test_human_review_rate_is_sane(report) -> None:
    """전량을 사람에게 넘기면 자동 채점의 의미가 없다. 상한 30%는 임의값이며 실측 후 조정한다."""
    assert report.needs_human_review_rate <= 0.30, (
        f"human review 비율 {report.needs_human_review_rate:.1%} 초과"
    )
