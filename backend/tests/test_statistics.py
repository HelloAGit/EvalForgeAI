from app.services.statistical_engine import StatisticalEngine

def test_paired_t_test_significance():
    baseline = [0.70, 0.72, 0.68, 0.75, 0.71]
    candidate = [0.85, 0.88, 0.84, 0.90, 0.86]
    
    result = StatisticalEngine.compare_performance(baseline, candidate)
    assert result["is_statistically_significant"] is True
    assert result["mean_difference"] > 0
