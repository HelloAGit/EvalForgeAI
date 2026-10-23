import math
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy import stats


def describe(values: Sequence[float], confidence: float = 0.95) -> Dict[str, Optional[float]]:
    """Descriptive statistics with a t-based confidence interval for the mean."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci_low": None, "ci_high": None}
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if n < 2:
        return {"n": n, "mean": mean, "std": None, "ci_low": None, "ci_high": None}
    std = float(arr.std(ddof=1))
    half = float(stats.t.ppf(1 - (1 - confidence) / 2, n - 1) * std / math.sqrt(n))
    return {"n": n, "mean": mean, "std": std, "ci_low": mean - half, "ci_high": mean + half}


def describe_from_sums(n: int, total: float, total_sq: float, confidence: float = 0.95):
    """Same as ``describe`` but from SQL aggregates (COUNT, SUM, SUM of squares)."""
    if n == 0:
        return describe([])
    mean = total / n
    if n < 2:
        return {"n": n, "mean": mean, "std": None, "ci_low": None, "ci_high": None}
    var = max((total_sq - n * mean * mean) / (n - 1), 0.0)
    std = math.sqrt(var)
    half = float(stats.t.ppf(1 - (1 - confidence) / 2, n - 1) * std / math.sqrt(n))
    return {"n": n, "mean": mean, "std": std, "ci_low": mean - half, "ci_high": mean + half}


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not len(values):
        return None
    return float(np.percentile(np.asarray(values, dtype=float), q))


def compare_samples(baseline: List[float], candidate: List[float], alpha: float = 0.05,
                    paired: bool = False) -> Dict[str, object]:
    """Welch (unpaired) or paired t-test with Cohen's d and a CI for the mean difference.
    Returns ``testable: False`` plus a reason when there is not enough data."""
    nb, nc = len(baseline), len(candidate)
    if nb < 2 or nc < 2:
        return {"testable": False, "reason": "At least 2 observations per group are required.",
                "n_baseline": nb, "n_candidate": nc}
    b = np.asarray(baseline, dtype=float)
    c = np.asarray(candidate, dtype=float)
    if paired:
        if nb != nc:
            return {"testable": False, "reason": "Paired comparison requires equal sample sizes.",
                    "n_baseline": nb, "n_candidate": nc}
        diffs = c - b
        sd = float(diffs.std(ddof=1))
        mean_diff = float(diffs.mean())
        if sd == 0:
            return {"testable": True, "method": "Paired Sample t-test", "n_baseline": nb, "n_candidate": nc,
                    "mean_difference": mean_diff, "p_value": 1.0 if mean_diff == 0 else 0.0,
                    "effect_size": None, "ci_low": mean_diff, "ci_high": mean_diff,
                    "significant": mean_diff != 0, "alpha": alpha}
        t_stat, p = stats.ttest_rel(c, b)
        half = float(stats.t.ppf(1 - alpha / 2, nb - 1) * sd / math.sqrt(nb))
        d = mean_diff / sd
        method = "Paired Sample t-test"
    else:
        mean_diff = float(c.mean() - b.mean())
        vb, vc = float(b.var(ddof=1)), float(c.var(ddof=1))
        if vb == 0 and vc == 0:
            return {"testable": True, "method": "Welch t-test", "n_baseline": nb, "n_candidate": nc,
                    "mean_difference": mean_diff, "p_value": 1.0 if mean_diff == 0 else 0.0,
                    "effect_size": None, "ci_low": mean_diff, "ci_high": mean_diff,
                    "significant": mean_diff != 0, "alpha": alpha}
        t_stat, p = stats.ttest_ind(c, b, equal_var=False)
        se = math.sqrt(vb / nb + vc / nc)
        dof = (vb / nb + vc / nc) ** 2 / ((vb / nb) ** 2 / (nb - 1) + (vc / nc) ** 2 / (nc - 1))
        half = float(stats.t.ppf(1 - alpha / 2, dof) * se)
        pooled = math.sqrt(((nb - 1) * vb + (nc - 1) * vc) / (nb + nc - 2))
        d = mean_diff / pooled if pooled > 0 else None
        method = "Welch t-test"
    return {"testable": True, "method": method, "n_baseline": nb, "n_candidate": nc,
            "mean_difference": mean_diff, "p_value": float(p), "effect_size": None if d is None else float(d),
            "ci_low": mean_diff - half, "ci_high": mean_diff + half,
            "significant": bool(p < alpha), "alpha": alpha}
