"""Eval suite for the optimisation agent: run it over many tasks and report how well it does.

Each task is a directory holding ``slow.py`` (the program to speed up) and, optionally,
``candidates/*.py`` (replayed by the scripted proposer for deterministic offline runs).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from benchmark_harness.agent import Proposer, ScriptedProposer, optimize


@dataclass
class TaskResult:
    task: str
    solved: bool
    attempts: int
    wall_delta_pct: float | None  # of the accepted candidate; None if unsolved

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvalSummary:
    results: list[TaskResult]

    @property
    def solve_rate(self) -> float:
        return sum(r.solved for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def mean_attempts_to_solve(self) -> float | None:
        solved = [r.attempts for r in self.results if r.solved]
        return sum(solved) / len(solved) if solved else None

    def to_dict(self) -> dict:
        return {
            "solve_rate": self.solve_rate,
            "mean_attempts_to_solve": self.mean_attempts_to_solve,
            "results": [r.to_dict() for r in self.results],
        }


def discover_tasks(tasks_dir: Path) -> list[Path]:
    """Task directories are sub-folders that contain a slow.py."""
    return sorted(d for d in tasks_dir.iterdir() if (d / "slow.py").is_file())


def run_eval(
    tasks_dir: Path,
    proposer_for: Callable[[Path], Proposer],
    *,
    runs: int = 10,
    warmup: int = 2,
    max_iterations: int = 5,
    on_event: Callable[[str], None] | None = None,
) -> EvalSummary:
    """Run the agent on every task (in a scratch copy, so the repo is never modified)."""
    say = on_event or (lambda _m: None)
    results: list[TaskResult] = []
    for task_dir in discover_tasks(tasks_dir):
        say(f"Task: {task_dir.name}")
        with tempfile.TemporaryDirectory() as scratch:
            work = Path(scratch) / "slow.py"
            shutil.copy(task_dir / "slow.py", work)
            report = optimize(
                work, f"python {work.as_posix()}", proposer_for(task_dir),
                runs=runs, warmup=warmup, max_iterations=max_iterations, on_event=None,
            )
        wall = next((c for c in report.final_comparisons if c.metric == "wall_s"), None)
        results.append(TaskResult(
            task=task_dir.name, solved=report.accepted, attempts=len(report.attempts),
            wall_delta_pct=wall.delta_pct if wall and report.accepted else None,
        ))
        say(f"  {'solved' if report.accepted else 'unsolved'} in {len(report.attempts)} attempt(s)")
    return EvalSummary(results)


def scripted_for(task_dir: Path) -> Proposer:
    return ScriptedProposer.from_directory(task_dir / "candidates")
