"""CLI entry point for the benchmark harness."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from benchmark_harness.reporter import to_json, to_markdown
from benchmark_harness.runner import BenchmarkResult, Sample, run_benchmark
from benchmark_harness.stats import ComparisonResult, Verdict, compare_all

console = Console()


def _summary_table(result: BenchmarkResult) -> Table:
    samples: list[Sample] = result.samples
    wall = [s.wall_s for s in samples]
    cpu = [s.cpu_s for s in samples]
    rss = [s.peak_rss_mb for s in samples]

    def fmt(values: list[float], unit: str) -> str:
        if not values:
            return "—"
        return f"{min(values):.4f} / {sum(values)/len(values):.4f} / {max(values):.4f} {unit}"

    table = Table(title=f"[bold]Benchmark: {result.label}[/bold]", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("min / mean / max", style="white")
    table.add_row("Wall time", fmt(wall, "s"))
    table.add_row("CPU time", fmt(cpu, "s"))
    table.add_row("Peak RSS", fmt(rss, "MB"))
    table.add_row("Runs", str(result.runs))
    table.add_row("Warmup", str(result.warmup))
    return table


@click.group()
@click.version_option()
def cli() -> None:
    """Performance Regression Benchmark Harness."""


@cli.command("run")
@click.argument("command")
@click.option("--label", "-l", default="benchmark", show_default=True,
              help="Label for this result set (e.g. 'before' or 'after').")
@click.option("--runs", "-n", default=20, show_default=True,
              help="Number of timed measurement runs.")
@click.option("--warmup", "-w", default=3, show_default=True,
              help="Number of un-timed warmup runs.")
@click.option("--out", "-o", default=None,
              help="Path to write results JSON (default: <label>.json).")
def run_cmd(command: str, label: str, runs: int, warmup: int, out: str | None) -> None:
    """Run COMMAND N times and save timing/memory results to a JSON file.

    \b
    Example:
        bench run "python my_script.py" --label before --runs 30 --warmup 5
    """
    out_path = Path(out) if out else Path(f"{label}.json")
    total = warmup + runs

    console.print(f"\n[bold cyan]Benchmarking:[/bold cyan] {command}")
    console.print(f"  Runs: [green]{runs}[/green]  Warmup: [yellow]{warmup}[/yellow]  → {out_path}\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running…", total=total)

        def _cb(current: int, total_runs: int) -> None:
            phase = "warmup" if current <= warmup else "measuring"
            progress.update(task, advance=1, description=f"[yellow]{phase}[/yellow] run {current}/{total_runs}")

        result = run_benchmark(command, label=label, runs=runs, warmup=warmup, progress_cb=_cb)

    result.save(out_path)
    console.print(_summary_table(result))
    console.print(f"\n[green]✓[/green] Results saved to [bold]{out_path}[/bold]\n")


_VERDICT_STYLE = {
    Verdict.REGRESSION: "bold red",
    Verdict.IMPROVEMENT: "bold green",
    Verdict.NO_CHANGE: "dim",
}

_METRIC_LABEL = {
    "wall_s": "Wall time",
    "cpu_s": "CPU time",
    "peak_rss_mb": "Peak RSS",
}


def _comparison_table(results: list[ComparisonResult], before_label: str, after_label: str) -> Table:
    table = Table(
        title=f"[bold]Comparison: {before_label} → {after_label}[/bold]",
        show_header=True,
    )
    table.add_column("Metric", style="cyan")
    table.add_column(f"{before_label} mean", justify="right")
    table.add_column(f"{after_label} mean", justify="right")
    table.add_column("Δ%", justify="right")
    table.add_column("p-value", justify="right")
    table.add_column("Cohen's d", justify="right")
    table.add_column("Verdict", justify="center")

    for r in results:
        style = _VERDICT_STYLE[r.verdict]
        unit = "s" if r.metric != "peak_rss_mb" else "MB"
        delta_str = f"{r.delta_pct:+.2f}%"
        table.add_row(
            _METRIC_LABEL.get(r.metric, r.metric),
            f"{r.before_mean:.4f} {unit}",
            f"{r.after_mean:.4f} {unit}",
            f"[{style}]{delta_str}[/{style}]",
            f"{r.p_value:.4f}",
            f"{r.cohens_d:+.3f}",
            f"[{style}]{r.verdict.value}[/{style}]",
        )
    return table


@cli.command("compare")
@click.argument("before_json", type=click.Path(exists=True, path_type=Path))
@click.argument("after_json", type=click.Path(exists=True, path_type=Path))
@click.option("--stat", "stat_method", default="ttest", show_default=True,
              type=click.Choice(["ttest", "bootstrap"]),
              help="Statistical test to use.")
@click.option("--alpha", default=0.05, show_default=True,
              help="Significance level (p-value threshold).")
@click.option("--min-effect", default=0.2, show_default=True,
              help="Minimum |Cohen's d| to treat a change as meaningful.")
@click.option("--metric", default="all", show_default=True,
              type=click.Choice(["wall_s", "cpu_s", "peak_rss_mb", "all"]),
              help="Metric to compare, or 'all' for all three.")
@click.option("--output", "-f", "output_format", default="console", show_default=True,
              type=click.Choice(["console", "json", "markdown"]),
              help="Output format. Use 'markdown' for CI/PR comments.")
@click.option("--report-out", default=None,
              help="Write the report to this file instead of stdout (json/markdown only).")
def compare_cmd(
    before_json: Path,
    after_json: Path,
    stat_method: str,
    alpha: float,
    min_effect: float,
    metric: str,
    output_format: str,
    report_out: str | None,
) -> None:
    """Compare BEFORE_JSON and AFTER_JSON and print a regression verdict.

    \b
    Examples:
        bench compare before.json after.json
        bench compare before.json after.json --stat bootstrap --output markdown
        bench compare before.json after.json --output markdown --report-out report.md
    """
    before = BenchmarkResult.load(before_json)
    after = BenchmarkResult.load(after_json)

    if metric == "all":
        comparisons = compare_all(before, after, stat_method=stat_method,  # type: ignore[arg-type]
                                  alpha=alpha, min_effect=min_effect)
    else:
        from benchmark_harness.stats import compare as _compare
        comparisons = [_compare(before, after, metric=metric,  # type: ignore[arg-type]
                                stat_method=stat_method, alpha=alpha, min_effect=min_effect)]

    verdicts = {r.verdict for r in comparisons}
    is_regression = Verdict.REGRESSION in verdicts

    if output_format == "json":
        text = to_json(comparisons, before, after)
        if report_out:
            Path(report_out).write_text(text, encoding="utf-8")
            console.print(f"[green]✓[/green] JSON report written to [bold]{report_out}[/bold]")
        else:
            import sys
            sys.stdout.buffer.write((text + "\n").encode("utf-8"))

    elif output_format == "markdown":
        text = to_markdown(comparisons, before, after)
        if report_out:
            Path(report_out).write_text(text, encoding="utf-8")
            console.print(f"[green]✓[/green] Markdown report written to [bold]{report_out}[/bold]")
        else:
            import sys
            sys.stdout.buffer.write((text + "\n").encode("utf-8"))

    else:  # console (default)
        console.print()
        console.print(_comparison_table(comparisons, before.label, after.label))
        console.print(
            f"\n  Method: [cyan]{stat_method}[/cyan]  "
            f"α=[cyan]{alpha}[/cyan]  "
            f"min |d|=[cyan]{min_effect}[/cyan]"
        )
        if is_regression:
            console.print("\n[bold red]✗ REGRESSION detected[/bold red]\n")
        elif Verdict.IMPROVEMENT in verdicts:
            console.print("\n[bold green]✓ IMPROVEMENT detected[/bold green]\n")
        else:
            console.print("\n[dim]— No significant change[/dim]\n")

    if is_regression:
        raise SystemExit(1)
