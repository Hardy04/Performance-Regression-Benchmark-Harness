"""Tests for the agentic optimisation loop (no network: proposers are scripted)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark_harness.agent import (
    Proposal,
    ScriptedProposer,
    extract_proposal,
    optimize,
)

SLOW = "import time\ntime.sleep(0.15)\nprint(42)\n"
FAST = "print(42)\n"
WRONG = "print(41)\n"
SLOWER = "import time\ntime.sleep(0.45)\nprint(42)\n"  # deterministic: clearly worse


@pytest.fixture()
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "target.py"
    target.write_text(SLOW, encoding="utf-8")
    return target


def _run(work: Path, candidates: list[Proposal], **kw):
    return optimize(work, "python target.py", ScriptedProposer(candidates), runs=5, warmup=1, **kw)


def test_retries_until_verified_improvement(work: Path) -> None:
    report = _run(work, [Proposal(WRONG, "wrong"), Proposal(SLOWER, "slower"), Proposal(FAST, "drop sleep")])
    assert report.accepted
    assert [a.accepted for a in report.attempts] == [False, False, True]
    assert report.attempts[0].output_matches is False       # correctness gate fired
    assert report.attempts[1].reason.startswith("regression")
    assert work.read_text(encoding="utf-8") == FAST          # winner left in place


def test_restores_original_when_nothing_improves(work: Path) -> None:
    report = _run(work, [Proposal(WRONG), Proposal(SLOWER)], max_iterations=5)
    assert not report.accepted
    assert len(report.attempts) == 2                         # proposer ran dry
    assert work.read_text(encoding="utf-8") == SLOW


def test_respects_max_iterations(work: Path) -> None:
    report = _run(work, [Proposal(WRONG)] * 4, max_iterations=2)
    assert len(report.attempts) == 2
    assert work.read_text(encoding="utf-8") == SLOW


def test_history_is_fed_back_to_proposer(work: Path) -> None:
    seen: list[int] = []

    class Spy:
        def propose(self, source: str, command: str, history: list) -> Proposal | None:
            seen.append(len(history))
            return Proposal(WRONG, "bad idea") if len(history) < 2 else None

    optimize(work, "python target.py", Spy(), runs=3, warmup=0, max_iterations=5)
    assert seen == [0, 1, 2]


def test_restores_on_exception(work: Path) -> None:
    class Boom:
        def propose(self, source: str, command: str, history: list) -> Proposal | None:
            work.write_text("print('half-written')", encoding="utf-8")
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        optimize(work, "python target.py", Boom(), runs=3, warmup=0)
    assert work.read_text(encoding="utf-8") == SLOW


def test_extract_proposal() -> None:
    p = extract_proposal("Use a formula.\n```python\nprint(1)\n```\nthanks")
    assert p is not None and p.source == "print(1)\n" and p.rationale == "Use a formula."
    assert extract_proposal("no code here") is None
