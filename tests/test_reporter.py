"""Tests for the reporter module."""

from __future__ import annotations

import json

from benchmark_harness.reporter import _COMMENT_MARKER, to_json, to_markdown
from benchmark_harness.runner import BenchmarkResult, Sample
from benchmark_harness.stats import Verdict, compare_all


def _make_result(label: str, wall_times: list[float]) -> BenchmarkResult:
    samples = [Sample(wall_s=w, cpu_s=0.0, peak_rss_mb=10.0) for w in wall_times]
    r = BenchmarkResult(label=label, command="dummy", runs=len(samples), warmup=0)
    r.samples = samples
    return r


def _regression_pair() -> tuple[BenchmarkResult, BenchmarkResult]:
    before = _make_result("before", [0.10 + i * 0.0001 for i in range(30)])
    after  = _make_result("after",  [0.50 + i * 0.0001 for i in range(30)])
    return before, after


def _improvement_pair() -> tuple[BenchmarkResult, BenchmarkResult]:
    before = _make_result("before", [0.50 + i * 0.0001 for i in range(30)])
    after  = _make_result("after",  [0.10 + i * 0.0001 for i in range(30)])
    return before, after


# --- JSON output ---

def test_json_output_is_valid_json():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    text = to_json(comparisons, before, after)
    data = json.loads(text)
    assert isinstance(data, dict)


def test_json_contains_required_keys():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    data = json.loads(to_json(comparisons, before, after))
    assert "overall_verdict" in data
    assert "metrics" in data
    assert data["before_label"] == "before"
    assert data["after_label"] == "after"


def test_json_overall_verdict_regression():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    data = json.loads(to_json(comparisons, before, after))
    assert data["overall_verdict"] == Verdict.REGRESSION.value


def test_json_overall_verdict_improvement():
    before, after = _improvement_pair()
    comparisons = compare_all(before, after)
    data = json.loads(to_json(comparisons, before, after))
    assert data["overall_verdict"] == Verdict.IMPROVEMENT.value


def test_json_metrics_have_required_fields():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    data = json.loads(to_json(comparisons, before, after))
    for m in data["metrics"]:
        assert "metric" in m
        assert "before_mean" in m
        assert "after_mean" in m
        assert "delta_pct" in m
        assert "p_value" in m
        assert "cohens_d" in m
        assert "verdict" in m


# --- Markdown output ---

def test_markdown_contains_comment_marker():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    md = to_markdown(comparisons, before, after)
    assert _COMMENT_MARKER in md


def test_markdown_contains_verdict_heading():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    md = to_markdown(comparisons, before, after)
    assert "REGRESSION" in md


def test_markdown_contains_table_header():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    md = to_markdown(comparisons, before, after)
    assert "| Metric |" in md
    assert "| Before |" in md


def test_markdown_improvement_verdict():
    before, after = _improvement_pair()
    comparisons = compare_all(before, after)
    md = to_markdown(comparisons, before, after)
    assert "IMPROVEMENT" in md


def test_markdown_contains_ci_details():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    md = to_markdown(comparisons, before, after)
    assert "95% CI" in md


def test_markdown_contains_test_settings():
    before, after = _regression_pair()
    comparisons = compare_all(before, after)
    md = to_markdown(comparisons, before, after)
    assert "Test settings" in md
    assert "alpha" in md.lower() or "α" in md
