"""Statistical significance engine: t-test and bootstrap comparison."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

import numpy as np
from scipy import stats

from benchmark_harness.runner import BenchmarkResult


class Verdict(str, Enum):
    REGRESSION = "REGRESSION"
    IMPROVEMENT = "IMPROVEMENT"
    NO_CHANGE = "NO_CHANGE"


@dataclass
class ComparisonResult:
    metric: str                  # "wall_s", "cpu_s", or "peak_rss_mb"
    before_mean: float
    after_mean: float
    delta_pct: float             # (after - before) / before * 100
    p_value: float
    cohens_d: float
    ci_low: float                # 95% CI on the delta (after - before)
    ci_high: float
    verdict: Verdict
    stat_method: str             # "ttest" or "bootstrap"
    alpha: float
    min_effect: float            # Cohen's d threshold used


def _cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Pooled Cohen's d (signed: positive = b > a)."""
    n_a, n_b = len(a), len(b)
    pooled_std = np.sqrt(
        ((n_a - 1) * a.std(ddof=1) ** 2 + (n_b - 1) * b.std(ddof=1) ** 2)
        / (n_a + n_b - 2)
    )
    if pooled_std == 0:
        return 0.0
    return float((b.mean() - a.mean()) / pooled_std)


def _bootstrap_ci(
    a: np.ndarray,
    b: np.ndarray,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng: np.random.Generator | None = None,
) -> tuple[float, float, float]:
    """
    Bootstrap percentile CI on (mean_b - mean_a).
    Returns (p_value, ci_low, ci_high).
    """
    rng = rng or np.random.default_rng(42)
    deltas = np.empty(n_resamples)
    for i in range(n_resamples):
        boot_a = rng.choice(a, size=len(a), replace=True)
        boot_b = rng.choice(b, size=len(b), replace=True)
        deltas[i] = boot_b.mean() - boot_a.mean()

    alpha = 1 - confidence
    ci_low = float(np.percentile(deltas, alpha / 2 * 100))
    ci_high = float(np.percentile(deltas, (1 - alpha / 2) * 100))

    # Two-sided p-value: proportion of bootstrap deltas on the opposite side of zero
    observed = float(b.mean() - a.mean())
    if observed >= 0:
        p_value = float(np.mean(deltas <= 0)) * 2
    else:
        p_value = float(np.mean(deltas >= 0)) * 2
    p_value = min(p_value, 1.0)

    return p_value, ci_low, ci_high


def compare(
    before: BenchmarkResult,
    after: BenchmarkResult,
    metric: Literal["wall_s", "cpu_s", "peak_rss_mb"] = "wall_s",
    stat_method: Literal["ttest", "bootstrap"] = "ttest",
    alpha: float = 0.05,
    min_effect: float = 0.2,
) -> ComparisonResult:
    """
    Compare two benchmark results on *metric* and return a ComparisonResult.

    A REGRESSION is declared only when BOTH conditions hold:
      1. p_value < alpha  (statistically significant)
      2. |cohens_d| >= min_effect  (practically meaningful)

    Args:
        before:      Result from the baseline run.
        after:       Result from the changed run.
        metric:      Which measurement to compare.
        stat_method: "ttest" (Welch's) or "bootstrap" (percentile CI).
        alpha:       Significance threshold.
        min_effect:  Minimum |Cohen's d| to treat the change as meaningful.
    """
    a = np.array([getattr(s, metric) for s in before.samples], dtype=float)
    b = np.array([getattr(s, metric) for s in after.samples], dtype=float)

    if len(a) < 2 or len(b) < 2:
        raise ValueError("Need at least 2 samples in each result to compare.")

    before_mean = float(a.mean())
    after_mean = float(b.mean())
    delta_pct = ((after_mean - before_mean) / before_mean * 100) if before_mean != 0 else 0.0
    d = _cohens_d(a, b)

    if stat_method == "ttest":
        t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)  # Welch's t-test
        p_value = float(p_value) if not np.isnan(p_value) else 1.0
        var_a = float(a.var(ddof=1))
        var_b = float(b.var(ddof=1))
        se_sq = var_a / len(a) + var_b / len(b)
        se = np.sqrt(se_sq)
        diff = after_mean - before_mean
        # Welch–Satterthwaite degrees of freedom (guard against zero variance)
        if se_sq == 0:
            ci_low = ci_high = diff
        else:
            denom = (var_a / len(a)) ** 2 / (len(a) - 1) + (var_b / len(b)) ** 2 / (len(b) - 1)
            df = se_sq ** 2 / denom if denom > 0 else float(len(a) + len(b) - 2)
            t_crit = float(stats.t.ppf(0.975, df))
            ci_low = float(diff - t_crit * se)
            ci_high = float(diff + t_crit * se)
    else:
        p_value, ci_low, ci_high = _bootstrap_ci(a, b)

    significant = p_value < alpha
    meaningful = abs(d) >= min_effect

    if significant and meaningful:
        verdict = Verdict.REGRESSION if d > 0 else Verdict.IMPROVEMENT
    else:
        verdict = Verdict.NO_CHANGE

    return ComparisonResult(
        metric=metric,
        before_mean=round(before_mean, 6),
        after_mean=round(after_mean, 6),
        delta_pct=round(delta_pct, 2),
        p_value=round(p_value, 6),
        cohens_d=round(d, 4),
        ci_low=round(ci_low, 6),
        ci_high=round(ci_high, 6),
        verdict=verdict,
        stat_method=stat_method,
        alpha=alpha,
        min_effect=min_effect,
    )


def compare_all(
    before: BenchmarkResult,
    after: BenchmarkResult,
    stat_method: Literal["ttest", "bootstrap"] = "ttest",
    alpha: float = 0.05,
    min_effect: float = 0.2,
) -> list[ComparisonResult]:
    """Run compare() for all three metrics and return results in a list."""
    results = []
    for metric in ("wall_s", "cpu_s", "peak_rss_mb"):
        try:
            results.append(
                compare(before, after, metric=metric,  # type: ignore[arg-type]
                        stat_method=stat_method, alpha=alpha, min_effect=min_effect)
            )
        except ValueError:
            pass
    return results
