from fastapi import APIRouter, HTTPException
from app.schemas.payload import StatAnalysisRequest, StatAnalysisResponse
from app.services.statistical_engine import StatisticalEngine

router = APIRouter(prefix="/api/v1/statistics", tags=["Statistical Engine"])

@router.post("/analyse", response_model=StatAnalysisResponse)
async def analyse_performance(payload: StatAnalysisRequest):
    res = StatisticalEngine.compare_performance(
        baseline=payload.baseline_scores,
        candidate=payload.candidate_scores,
        alpha=payload.alpha
    )
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])

    return StatAnalysisResponse(
        metric_name=payload.metric_name,
        sample_size=res["sample_size"],
        mean_difference=res["mean_difference"],
        p_value=res["p_value"],
        is_statistically_significant=res["is_statistically_significant"],
        confidence_interval=res["confidence_interval"],
        method=res["method"]
    )
