"""CLI smoke tests: catches import/syntax breakage and checks the CI gate's exit codes."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from benchmark_harness.cli import cli


def test_all_commands_register() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in ("run", "compare", "comment", "optimize", "eval"):
        assert name in result.output


def test_eval_gate_fails_below_min_solve_rate(tmp_path: Path) -> None:
    task = tmp_path / "t"
    (task / "candidates").mkdir(parents=True)
    (task / "slow.py").write_text("import time\ntime.sleep(0.1)\nprint(1)\n")
    (task / "candidates" / "1_wrong.py").write_text("print(2)\n")  # never correct → unsolved
    result = CliRunner().invoke(
        cli, ["eval", str(tmp_path), "--proposer", "scripted", "-n", "3", "--min-solve-rate", "1.0"])
    assert result.exit_code == 1
