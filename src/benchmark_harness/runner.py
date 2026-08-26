"""Benchmark runner: executes a shell command N times and collects timing/memory samples."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import psutil


@dataclass
class Sample:
    wall_s: float       # wall-clock seconds
    cpu_s: float        # user+sys CPU seconds consumed by the child process
    peak_rss_mb: float  # peak resident set size in MB


@dataclass
class BenchmarkResult:
    label: str
    command: str
    runs: int
    warmup: int
    samples: list[Sample] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BenchmarkResult":
        samples = [Sample(**s) for s in d.pop("samples", [])]
        result = cls(**d)
        result.samples = samples
        return result

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "BenchmarkResult":
        return cls.from_dict(json.loads(path.read_text()))


def _run_once(cmd: Sequence[str]) -> Sample:
    """Run a command once and return a single Sample."""
    t_start = time.perf_counter()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    peak_rss_bytes = 0
    ps_proc = None
    try:
        ps_proc = psutil.Process(proc.pid)
    except psutil.NoSuchProcess:
        pass

    while proc.poll() is None:
        if ps_proc is not None:
            try:
                # Includes memory of child processes
                rss = ps_proc.memory_info().rss
                children_rss = sum(c.memory_info().rss for c in ps_proc.children(recursive=True))
                peak_rss_bytes = max(peak_rss_bytes, rss + children_rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(0.005)

    t_end = time.perf_counter()
    wall_s = t_end - t_start

    # CPU time from process resource usage
    try:
        cpu_times = ps_proc.cpu_times() if ps_proc else None
        cpu_s = (cpu_times.user + cpu_times.system) if cpu_times else 0.0
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        cpu_s = 0.0

    # Fall back to a final RSS snapshot if polling captured nothing
    if peak_rss_bytes == 0 and ps_proc is not None:
        try:
            peak_rss_bytes = ps_proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return Sample(
        wall_s=round(wall_s, 6),
        cpu_s=round(cpu_s, 6),
        peak_rss_mb=round(peak_rss_bytes / (1024 * 1024), 4),
    )


def run_benchmark(
    command: str,
    label: str,
    runs: int = 20,
    warmup: int = 3,
    progress_cb: "callable[[int, int], None] | None" = None,
) -> BenchmarkResult:
    """
    Execute *command* (runs + warmup) times, return a BenchmarkResult.

    Args:
        command: Shell command string to benchmark.
        label:   Human-readable label (e.g. "before", "after").
        runs:    Number of timed measurement runs.
        warmup:  Number of un-timed warmup runs (JIT, cache warm-up, etc.).
        progress_cb: Optional callback(current_run, total_runs) for progress display.
    """
    cmd = shlex.split(command, posix=(sys.platform != "win32"))
    total = warmup + runs
    result = BenchmarkResult(label=label, command=command, runs=runs, warmup=warmup)

    for i in range(total):
        if progress_cb:
            progress_cb(i + 1, total)
        sample = _run_once(cmd)
        if i >= warmup:
            result.samples.append(sample)

    return result
