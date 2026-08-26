"""Tests for the benchmark runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from benchmark_harness.runner import BenchmarkResult, Sample, run_benchmark


PYTHON = sys.executable

# A fast command that exits immediately — used to verify structure, not timing.
FAST_CMD = f"{PYTHON} -c \"print('ok')\""


def test_run_returns_correct_sample_count():
    result = run_benchmark(FAST_CMD, label="test", runs=5, warmup=1)
    assert len(result.samples) == 5


def test_warmup_not_included_in_samples():
    result = run_benchmark(FAST_CMD, label="test", runs=3, warmup=2)
    # Only timed runs are stored
    assert len(result.samples) == 3


def test_sample_fields_are_non_negative():
    result = run_benchmark(FAST_CMD, label="test", runs=3, warmup=0)
    for s in result.samples:
        assert s.wall_s >= 0
        assert s.cpu_s >= 0
        assert s.peak_rss_mb >= 0


def test_save_and_load_roundtrip(tmp_path: Path):
    result = run_benchmark(FAST_CMD, label="roundtrip", runs=2, warmup=0)
    out = tmp_path / "result.json"
    result.save(out)

    loaded = BenchmarkResult.load(out)
    assert loaded.label == result.label
    assert loaded.runs == result.runs
    assert len(loaded.samples) == len(result.samples)
    assert loaded.samples[0].wall_s == result.samples[0].wall_s


def test_result_json_is_valid(tmp_path: Path):
    result = run_benchmark(FAST_CMD, label="json_check", runs=2, warmup=0)
    out = tmp_path / "result.json"
    result.save(out)
    data = json.loads(out.read_text())
    assert data["label"] == "json_check"
    assert isinstance(data["samples"], list)
    assert "wall_s" in data["samples"][0]
