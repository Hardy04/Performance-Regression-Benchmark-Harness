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


@cli.command("comment")
@click.argument("report_md", type=click.Path(exists=True, path_type=Path))
@click.option("--repo", required=True, envvar="GITHUB_REPOSITORY",
              help="GitHub repo in owner/name format (auto-set in Actions via GITHUB_REPOSITORY).")
@click.option("--pr", "pr_number", required=True, type=int, envvar="PR_NUMBER",
              help="Pull request number.")
@click.option("--token", default=None, envvar="GITHUB_TOKEN",
              help="GitHub token (default: GITHUB_TOKEN env var).")
def comment_cmd(report_md: Path, repo: str, pr_number: int, token: str | None) -> None:
    """Post or update a PR comment with the Markdown report.

    \b
    Example (in CI):
        bench comment report.md --repo owner/repo --pr 42
    """
    from benchmark_harness.gh_comment import post_or_update_comment

    console.print(f"\nPosting report to [bold]{repo}[/bold] PR [cyan]#{pr_number}[/cyan]…")
    try:
        url = post_or_update_comment(report_md, repo=repo, pr_number=pr_number, token=token)
        console.print(f"[green]✓[/green] Comment posted: {url}\n")
    except Exception as exc:
        console.print(f"[red]✗ Failed to post comment:[/red] {exc}\n")
        raise SystemExit(1)


@cli.command("optimize")
@click.argument("target", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--command", "-c", required=True,
              help="Shell command that executes TARGET, e.g. 'python work.py'.")
@click.option("--proposer", "proposer_kind", default="anthropic", show_default=True,
              type=click.Choice(["anthropic", "ollama", "scripted"]),
              help="Who proposes fixes. 'ollama' = free local model. 'scripted' replays files from --candidates (offline demo).")
@click.option("--candidates", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="Directory of candidate .py files for --proposer scripted.")
@click.option("--model", default=None, help="Model for anthropic (default claude-sonnet-5-5) or ollama (default qwen2.5-coder:7b).")
@click.option("--max-iterations", default=5, show_default=True, help="Maximum propose/verify cycles.")
@click.option("--runs", "-n", default=10, show_default=True, help="Timed runs per measurement.")
@click.option("--warmup", "-w", default=2, show_default=True, help="Warmup runs per measurement.")
@click.option("--alpha", default=0.05, show_default=True, help="Significance level.")
@click.option("--min-effect", default=0.2, show_default=True, help="Minimum |Cohen's d|.")
@click.option("--report-out", default=None, help="Write the attempt log as JSON to this path.")
def optimize_cmd(
    target: Path,
    command: str,
    proposer_kind: str,
    candidates: Path | None,
    model: str | None,
    max_iterations: int,
    runs: int,
    warmup: int,
    alpha: float,
    min_effect: float,
    report_out: str | None,
) -> None:
    """Let an agent propose a fix for TARGET; the harness verifies it and retries if needed.

    The agent's file edit is accepted only if stdout is unchanged AND the statistics engine reports
    a significant wall-time improvement with no regressions. Otherwise it is reverted and the agent
    retries with the measured numbers. NOTE: this executes model-written code — use a scratch copy.

    \b
    Example:
        bench optimize work.py -c "python work.py" --max-iterations 5
    """
    import json

    from benchmark_harness.agent import make_proposer, optimize

    try:
        proposer = make_proposer(proposer_kind, model, candidates)
    except Exception as exc:
        raise click.ClickException(str(exc))

    console.print(f"\n[bold cyan]Optimising:[/bold cyan] {target}  ([dim]{command}[/dim])\n")
    try:
        report = optimize(
            target, command, proposer, runs=runs, warmup=warmup, max_iterations=max_iterations,
            alpha=alpha, min_effect=min_effect, on_event=lambda m: console.print(f"  {m}"),
        )
    except RuntimeError as exc:  # e.g. Ollama not running; the target file has been restored
        raise click.ClickException(str(exc))

    if report_out:
        Path(report_out).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    if report.accepted:
        console.print(_comparison_table(report.final_comparisons, "baseline", "candidate"))
        console.print(f"\n[bold green]✓ Verified improvement after {len(report.attempts)} attempt(s)"
                      f" — {target} updated[/bold green]\n")
    else:
        console.print(f"\n[bold red]✗ No verified improvement after {len(report.attempts)} attempt(s)"
                      f" — {target} left unchanged[/bold red]\n")
        raise SystemExit(1)


@cli.command("eval")
@click.argument("tasks_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--proposer", "proposer_kind", default="anthropic", show_default=True,
              type=click.Choice(["anthropic", "ollama", "scripted"]),
              help="'ollama' = free local model. 'scripted' replays each task's candidates/ folder (deterministic, offline).")
@click.option("--model", default=None, help="Model for anthropic (default claude-sonnet-5-5) or ollama (default qwen2.5-coder:7b).")
@click.option("--max-iterations", default=5, show_default=True, help="Attempts allowed per task.")
@click.option("--runs", "-n", default=10, show_default=True, help="Timed runs per measurement.")
@click.option("--report-out", default=None, help="Write the eval summary as JSON to this path.")
@click.option("--min-solve-rate", default=0.0, show_default=True, type=click.FloatRange(0.0, 1.0),
              help="Exit with code 1 if the solve rate is below this (for CI gating).")
def eval_cmd(tasks_dir: Path, proposer_kind: str, model: str | None,
             max_iterations: int, runs: int, report_out: str | None, min_solve_rate: float) -> None:
    """Score the optimisation agent across every task in TASKS_DIR.

    Reports solve rate and mean attempts-to-solve, so changes to the agent (prompt, model,
    verification rules) can be compared with numbers rather than anecdotes.

    \b
    Example:
        bench eval examples/tasks --proposer scripted
    """
    import json

    from benchmark_harness.agent import make_proposer
    from benchmark_harness.evals import run_eval, scripted_for

    if proposer_kind == "scripted":
        factory = scripted_for
    else:
        try:
            shared = make_proposer(proposer_kind, model)
        except Exception as exc:
            raise click.ClickException(str(exc))
        factory = lambda _task_dir: shared  # noqa: E731 - stateless, safe to share

    console.print(f"\n[bold cyan]Evaluating agent on[/bold cyan] {tasks_dir}\n")
    try:
        summary = run_eval(tasks_dir, factory, runs=runs, max_iterations=max_iterations,
                           on_event=lambda m: console.print(f"  {m}"))
    except RuntimeError as exc:
        raise click.ClickException(str(exc))

    table = Table(title="[bold]Agent eval[/bold]", show_header=True)
    table.add_column("Task", style="cyan")
    table.add_column("Solved", justify="center")
    table.add_column("Attempts", justify="right")
    table.add_column("Wall Δ%", justify="right")
    for r in summary.results:
        table.add_row(r.task, "[green]yes[/green]" if r.solved else "[red]no[/red]", str(r.attempts),
                      f"{r.wall_delta_pct:+.1f}%" if r.wall_delta_pct is not None else "—")
    console.print(table)
    mean = summary.mean_attempts_to_solve
    console.print(f"\n  Solve rate: [bold]{summary.solve_rate:.0%}[/bold]   "
                  f"Mean attempts to solve: [bold]{'—' if mean is None else f'{mean:.1f}'}[/bold]\n")
    if report_out:
        Path(report_out).write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    if summary.solve_rate < min_solve_rate:
        console.print(f"[bold red]✗ Solve rate {summary.solve_rate:.0%} is below the required "
                      f"{min_solve_rate:.0%}[/bold red]\n")
        raise SystemExit(1)
