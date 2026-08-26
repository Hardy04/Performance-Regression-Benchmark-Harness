"""Tests for the statistics engine."""

from __future__ import annotations

import pytest
import numpy as np

from benchmark_harness.runner import BenchmarkResult, Sample
from benchmark_harness.stats import Verdict, compare, compare_all, _cohens_d


def _make_result(label: str, wall_times: list[float], rss: float = 10.0) -> BenchmarkResult:
    samples = [Sample(wall_s=w, cpu_s=0.0, peak_rss_mb=rss) for w in wall_times]
    r = BenchmarkResult(label=label, command="dummy", runs=len(samples), warmup=0)
    r.samples = samples
    return r


# --- Cohen's d ---

def test_cohens_d_identical_samples_returns_zero():
    a = np.array([1.0, 1.0, 1.0])
    b = np.array([1.0, 1.0, 1.0])
    assert _cohens_d(a, b) == 0.0


def test_cohens_d_sign_positive_when_b_larger():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=1.0, scale=0.1, size=50)
    b = rng.normal(loc=2.0, scale=0.1, size=50)
    assert _cohens_d(a, b) > 0


def test_cohens_d_sign_negative_when_b_smaller():
    rng = np.random.default_rng(0)
    a = rng.normal(loc=2.0, scale=0.1, size=50)
    b = rng.normal(loc=1.0, scale=0.1, size=50)
    assert _cohens_d(a, b) < 0


# --- t-test compare ---

def test_no_change_when_distributions_identical():
    times = [0.1 + i * 0.001 for i in range(20)]
    before = _make_result("before", times)
    after = _make_result("after", times[:])
    result = compare(before, after, stat_method="ttest")
    assert result.verdict == Verdict.NO_CHANGE


def test_regression_detected_on_clear_slowdown():
    before = _make_result("before", [0.10 + i * 0.0001 for i in range(30)])
    after = _make_result("after",  [0.50 + i * 0.0001 for i in range(30)])
    result = compare(before, after, stat_method="ttest", alpha=0.05, min_effect=0.2)
    assert result.verdict == Verdict.REGRESSION


def test_improvement_detected_on_clear_speedup():
    before = _make_result("before", [0.50 + i * 0.0001 for i in range(30)])
    after = _make_result("after",  [0.10 + i * 0.0001 for i in range(30)])
    result = compare(before, after, stat_method="ttest", alpha=0.05, min_effect=0.2)
    assert result.verdict == Verdict.IMPROVEMENT


def test_no_regression_when_effect_below_min_effect():
    # High variance, tiny mean shift → d << threshold, should be NO_CHANGE
    rng = np.random.default_rng(7)
    before_times = (rng.normal(loc=1.0, scale=1.0, size=50)).tolist()
    after_times  = (rng.normal(loc=1.01, scale=1.0, size=50)).tolist()  # d ≈ 0.01, min_effect=0.5
    before = _make_result("before", before_times)
    after  = _make_result("after",  after_times)
    result = compare(before, after, stat_method="ttest", alpha=0.05, min_effect=0.5)
    assert result.verdict == Verdict.NO_CHANGE


def test_delta_pct_sign_and_magnitude():
    before = _make_result("before", [1.0] * 20)
    after = _make_result("after",  [1.5] * 20)
    result = compare(before, after)
    assert abs(result.delta_pct - 50.0) < 0.01


def test_raises_on_too_few_samples():
    before = _make_result("before", [0.1])
    after = _make_result("after", [0.2])
    with pytest.raises(ValueError, match="at least 2"):
        compare(before, after)


# --- bootstrap compare ---

def test_bootstrap_regression_detected():
    before = _make_result("before", [0.10 + i * 0.0001 for i in range(30)])
    after = _make_result("after",  [0.50 + i * 0.0001 for i in range(30)])
    result = compare(before, after, stat_method="bootstrap", alpha=0.05, min_effect=0.2)
    assert result.verdict == Verdict.REGRESSION


def test_bootstrap_no_change_on_identical():
    times = [0.1 + i * 0.001 for i in range(20)]
    before = _make_result("before", times)
    after = _make_result("after", times[:])
    result = compare(before, after, stat_method="bootstrap")
    assert result.verdict == Verdict.NO_CHANGE


# --- compare_all ---

def test_compare_all_returns_three_metrics():
    before = _make_result("before", [0.1] * 10)
    after = _make_result("after",  [0.1] * 10)
    results = compare_all(before, after)
    metrics = [r.metric for r in results]
    assert "wall_s" in metrics
    assert "cpu_s" in metrics
    assert "peak_rss_mb" in metrics
