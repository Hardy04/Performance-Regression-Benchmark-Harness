"""Agentic optimisation loop: an LLM proposes a fix, the harness verifies it, retry on failure.

The harness is the *objective judge*. A candidate is accepted only if:

1. it produces byte-identical stdout to the original (correctness gate), and
2. the statistics engine reports an IMPROVEMENT on wall time (p < alpha and |d| >= min_effect)
   with no REGRESSION on any other metric.

Otherwise the candidate is reverted and the proposer is called again with the measured numbers
from every failed attempt, up to ``max_iterations``.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from benchmark_harness.runner import BenchmarkResult, run_benchmark
from benchmark_harness.stats import ComparisonResult, Verdict, compare_all

DEFAULT_MODEL = "claude-sonnet-5-5"


# --------------------------------------------------------------------------- data types


@dataclass
class Proposal:
    """A candidate replacement for the target file."""

    source: str
    rationale: str = ""


@dataclass
class Attempt:
    """Outcome of one propose → verify cycle."""

    iteration: int
    rationale: str
    accepted: bool
    reason: str
    output_matches: bool
    wall_delta_pct: float | None = None
    p_value: float | None = None
    cohens_d: float | None = None
    peak_rss_delta_pct: float | None = None

    def summary(self) -> str:
        """One-line description fed back to the proposer."""
        if not self.output_matches:
            return f"Attempt {self.iteration}: REJECTED — {self.reason}. Idea was: {self.rationale}"
        return (
            f"Attempt {self.iteration}: REJECTED — {self.reason} "
            f"(wall {self.wall_delta_pct:+.2f}%, p={self.p_value:.4f}, d={self.cohens_d:+.2f}). "
            f"Idea was: {self.rationale}"
        )


@dataclass
class OptimizeReport:
    target: str
    command: str
    accepted: bool
    attempts: list[Attempt] = field(default_factory=list)
    final_comparisons: list[ComparisonResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class Proposer(Protocol):
    """Anything that can suggest a new version of the target file."""

    def propose(self, source: str, command: str, history: list[Attempt]) -> Proposal | None:
        """Return a new full-file candidate, or None if out of ideas."""
        ...


# --------------------------------------------------------------------------- proposers


class ScriptedProposer:
    """Replays a fixed list of candidates. Offline demo + deterministic tests (no API key)."""

    def __init__(self, candidates: list[Proposal]) -> None:
        self._queue = list(candidates)

    @classmethod
    def from_directory(cls, directory: Path) -> "ScriptedProposer":
        files = sorted(directory.glob("*.py"))
        return cls([Proposal(f.read_text(encoding="utf-8"), f"scripted candidate {f.name}") for f in files])

    def propose(self, source: str, command: str, history: list[Attempt]) -> Proposal | None:
        return self._queue.pop(0) if self._queue else None


_SYSTEM_PROMPT = """You are a performance engineer. You are given a source file and the shell command \
that benchmarks it. Rewrite the file so the command runs measurably faster.

Hard rules:
- The command's stdout must stay byte-for-byte identical. A correctness check enforces this.
- Return the COMPLETE replacement file in a single ```python fenced block.
- Before the code block, write one or two sentences stating the idea.
- If earlier attempts are listed, they were measured and rejected. Do not repeat them; \
use the numbers to decide what to try next."""


def extract_proposal(text: str) -> Proposal | None:
    """Pull the rationale and the fenced python block out of an LLM reply."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, flags=re.DOTALL)
    if not match:
        return None
    return Proposal(source=match.group(1), rationale=text[: match.start()].strip())


class AnthropicProposer:
    """Asks a Claude model for a faster version of the target file."""

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 4096) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError('Install the agent extra first:  pip install -e ".[agent]"') from exc
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self._model = model
        self._max_tokens = max_tokens

    def propose(self, source: str, command: str, history: list[Attempt]) -> Proposal | None:
        parts = [f"Benchmark command:\n{command}\n", f"Current file:\n```python\n{source}\n```"]
        if history:
            parts.append("Rejected attempts so far:\n" + "\n".join(a.summary() for a in history))
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return extract_proposal(text)


# --------------------------------------------------------------------------- verification


def capture_stdout(command: str, timeout_s: float = 120.0) -> tuple[int, str]:
    """Run *command* once and return (returncode, stdout). Used as the correctness oracle."""
    cmd = shlex.split(command, posix=(sys.platform != "win32"))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return -1, ""
    return proc.returncode, proc.stdout


def judge(comparisons: list[ComparisonResult]) -> tuple[bool, str]:
    """Objective accept/reject decision from the statistics engine."""
    by_metric = {c.metric: c for c in comparisons}
    wall = by_metric.get("wall_s")
    if wall is None:
        return False, "no wall-time comparison available"
    regressed = [c.metric for c in comparisons if c.verdict is Verdict.REGRESSION]
    if regressed:
        return False, f"regression on {', '.join(regressed)}"
    if wall.verdict is not Verdict.IMPROVEMENT:
        return False, "no statistically significant wall-time improvement"
    return True, "significant wall-time improvement, no regressions"


# --------------------------------------------------------------------------- the loop


def optimize(
    target: Path,
    command: str,
    proposer: Proposer,
    *,
    runs: int = 10,
    warmup: int = 2,
    max_iterations: int = 5,
    stat_method: str = "ttest",
    alpha: float = 0.05,
    min_effect: float = 0.2,
    on_event: Callable[[str], None] | None = None,
) -> OptimizeReport:
    """Run the propose → verify → retry loop against *target*.

    *command* must execute *target* (e.g. ``python work.py``). On success the accepted candidate is
    left in place; on failure, or on any exception/Ctrl-C, the original file is restored.
    """
    say = on_event or (lambda _msg: None)
    original = target.read_text(encoding="utf-8")
    report = OptimizeReport(target=str(target), command=command, accepted=False)

    say("Measuring baseline…")
    base_rc, base_out = capture_stdout(command)
    if base_rc != 0:
        raise RuntimeError(f"Baseline command failed (exit {base_rc}); nothing to optimise.")
    baseline: BenchmarkResult = run_benchmark(command, label="baseline", runs=runs, warmup=warmup)

    try:
        for i in range(1, max_iterations + 1):
            say(f"Iteration {i}/{max_iterations}: asking proposer…")
            proposal = proposer.propose(original, command, report.attempts)
            if proposal is None:
                say("Proposer has no more ideas.")
                break

            target.write_text(proposal.source, encoding="utf-8")
            rc, out = capture_stdout(command)
            if rc != 0 or out != base_out:
                reason = "candidate crashed" if rc != 0 else "stdout differs from the original"
                report.attempts.append(Attempt(i, proposal.rationale, False, reason, output_matches=False))
                say(f"  ✗ {reason}")
                target.write_text(original, encoding="utf-8")
                continue

            candidate = run_benchmark(command, label=f"candidate-{i}", runs=runs, warmup=warmup)
            comparisons = compare_all(
                baseline, candidate, stat_method=stat_method,  # type: ignore[arg-type]
                alpha=alpha, min_effect=min_effect,
            )
            accepted, reason = judge(comparisons)
            by_metric = {c.metric: c for c in comparisons}
            wall, rss = by_metric["wall_s"], by_metric.get("peak_rss_mb")
            report.attempts.append(Attempt(
                i, proposal.rationale, accepted, reason, output_matches=True,
                wall_delta_pct=wall.delta_pct, p_value=wall.p_value, cohens_d=wall.cohens_d,
                peak_rss_delta_pct=rss.delta_pct if rss else None,
            ))
            say(f"  {'✓' if accepted else '✗'} wall {wall.delta_pct:+.2f}% p={wall.p_value:.4f} — {reason}")

            if accepted:
                report.accepted = True
                report.final_comparisons = comparisons
                return report
            target.write_text(original, encoding="utf-8")
    except BaseException:
        target.write_text(original, encoding="utf-8")
        raise

    target.write_text(original, encoding="utf-8")
    return report
