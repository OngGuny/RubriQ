"""골든셋으로 채점기를 평가하고 결과표를 낸다.

    uv run python scripts/run_eval.py --set eval/golden/ellipse-50.jsonl

**실제 LLM을 호출한다. 비용이 든다.** 골든셋 크기 × 호출 1회 = 총 호출 수.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from eval.harness import check_regression, evaluate, format_violations, load_golden_set
from rubriq.baseline.single_prompt import SinglePromptGrader
from rubriq.config import get_settings
from rubriq.llm.anthropic_client import AnthropicStructuredLLM

app = typer.Typer(add_completion=False)


@app.command()
def main(
    golden_set: Annotated[Path, typer.Option("--set", help="골든셋 jsonl 경로")],
    model: Annotated[str, typer.Option(help="모델 ID")] = "claude-opus-5",
    effort: Annotated[str, typer.Option(help="low|medium|high|xhigh|max")] = "medium",
    prompt_version: Annotated[str, typer.Option(help="프롬프트 버전")] = "v1",
    no_cache: Annotated[bool, typer.Option("--no-cache", help="프롬프트 캐싱 끄기")] = False,
    limit: Annotated[int, typer.Option(help="앞에서 N건만 (0이면 전체)")] = 0,
    out: Annotated[Path, typer.Option(help="리포트 출력 디렉토리")] = Path("eval/reports"),
) -> None:
    from rubriq.llm.anthropic_client import VALID_EFFORTS

    if effort not in VALID_EFFORTS:
        raise typer.BadParameter(f"effort must be one of {VALID_EFFORTS}")

    items = load_golden_set(golden_set)
    if limit:
        items = items[:limit]

    from rubriq.prompts.registry import load_prompt

    prompt = load_prompt("scoring", prompt_version)
    llm = AnthropicStructuredLLM(
        model=model,
        effort=effort,  # type: ignore[arg-type]  # 위에서 검증됨
        enable_caching=not no_cache,
    )
    grader = SinglePromptGrader(llm, prompt=prompt)

    typer.echo(f"채점 시작: {len(items)}건 · {model} · effort={effort} · {prompt.id}")
    typer.echo(f"  프롬프트 지문: {prompt.fingerprint} · 캐싱: {'off' if no_cache else 'on'}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = evaluate(
        grader,
        items,
        metadata={
            "golden_set": golden_set.name,
            "model": model,
            "effort": effort,
            "prompt_id": prompt.id,
            "prompt_fingerprint": prompt.fingerprint,
            "caching": "off" if no_cache else "on",
            "timestamp": stamp,
        },
    )
    path = report.write_json(out / f"eval-{stamp}.json")

    typer.echo("")
    typer.echo(f"{'항목':<14}{'QWK':>8}{'인접':>8}{'정확':>8}")
    typer.echo("-" * 38)
    for d in report.per_dimension:
        qwk = f"{d.qwk:.3f}" if d.qwk is not None else "  n/a"
        typer.echo(
            f"{d.dimension.value:<14}{qwk:>8}{d.adjacent_accuracy:>8.3f}{d.exact_accuracy:>8.3f}"
        )
    mean = report.mean_qwk
    typer.echo("-" * 38)
    typer.echo(f"{'평균 QWK':<14}{f'{mean:.3f}' if mean is not None else '  n/a':>8}")
    typer.echo("")
    typer.echo(f"latency  p50 {report.latency.p50:.0f}ms · p95 {report.latency.p95:.0f}ms")
    typer.echo(f"human review 비율  {report.needs_human_review_rate:.1%}")
    if report.failures:
        typer.echo(f"채점 실패  {len(report.failures)}건")
        for f in report.failures[:5]:
            typer.echo(f"  - {f}")
    typer.echo(f"리포트  {path}")

    violations = check_regression(report, get_settings().regression_qwk_threshold)
    if violations:
        typer.echo("")
        typer.echo(format_violations(violations))
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
