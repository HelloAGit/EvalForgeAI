import numpy as np
from scipy import stats
from typing import List, Dict, Any

class StatisticalEngine:
    @staticmethod
    def compare_performance(baseline: List[float], candidate: List[float], alpha: float = 0.05) -> Dict[str, Any]:
        arr_base = np.array(baseline)
        arr_cand = np.array(candidate)

        if len(arr_base) != len(arr_cand) or len(arr_base) < 2:
            return {
                "error": "Dataset lengths must be equal and contain at least 2 samples for paired analysis."
            }

        diffs = arr_cand - arr_base
        mean_diff = float(np.mean(diffs))
        
        t_stat, p_val = stats.ttest_rel(arr_cand, arr_base)
        
        std_err = float(stats.sem(diffs))
        ci_range = float(stats.t.ppf(1 - alpha / 2, len(diffs) - 1) * std_err)

        return {
            "sample_size": len(arr_base),
            "mean_difference": mean_diff,
            "p_value": float(p_val),
            "is_statistically_significant": bool(p_val < alpha),
            "confidence_interval": [mean_diff - ci_range, mean_diff + ci_range],
            "method": "Paired Sample t-test"
        }
