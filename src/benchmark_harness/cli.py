"""CLI entry point for the benchmark harness."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from benchmark_harness.runner import BenchmarkResult, Sample, run_benchmark

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
