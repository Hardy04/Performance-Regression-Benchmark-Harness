"""Tests for the agent eval suite (scripted proposer, no network)."""

from __future__ import annotations

from pathlib import Path

from benchmark_harness.evals import EvalSummary, TaskResult, discover_tasks, run_eval, scripted_for


def test_summary_metrics() -> None:
    s = EvalSummary([TaskResult("a", True, 2, -50.0), TaskResult("b", True, 4, -30.0), TaskResult("c", False, 5, None)])
    assert abs(s.solve_rate - 2 / 3) < 1e-9
    assert s.mean_attempts_to_solve == 3.0
    assert EvalSummary([]).solve_rate == 0.0 and EvalSummary([]).mean_attempts_to_solve is None


def test_discover_tasks(tmp_path: Path) -> None:
    (tmp_path / "t1").mkdir(); (tmp_path / "t1" / "slow.py").write_text("print(1)")
    (tmp_path / "not_a_task").mkdir()
    assert [d.name for d in discover_tasks(tmp_path)] == ["t1"]


def test_run_eval_on_one_task_leaves_repo_untouched(tmp_path: Path, monkeypatch) -> None:
    task = tmp_path / "tasks" / "t"
    (task / "candidates").mkdir(parents=True)
    slow = "import time\ntime.sleep(0.15)\nprint(7)\n"
    (task / "slow.py").write_text(slow)
    (task / "candidates" / "1_wrong.py").write_text("print(8)\n")
    (task / "candidates" / "2_fast.py").write_text("print(7)\n")
    summary = run_eval(tmp_path / "tasks", scripted_for, runs=5, warmup=1)
    assert summary.results[0].solved and summary.results[0].attempts == 2
    assert (task / "slow.py").read_text() == slow
