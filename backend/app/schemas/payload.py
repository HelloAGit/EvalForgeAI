from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class HealthResponse(BaseModel):
    status: str
    environment: str
    mubit_configured: bool

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str

class MubitStatusResponse(BaseModel):
    configured: bool
    base_url: str
    model: str
    connection_active: bool
    message: str

class StatAnalysisRequest(BaseModel):
    baseline_scores: List[float]
    candidate_scores: List[float]
    metric_name: str
    alpha: float = 0.05

class StatAnalysisResponse(BaseModel):
    metric_name: str
    sample_size: int
    mean_difference: float
    p_value: float
    is_statistically_significant: bool
    confidence_interval: List[float]
    method: str
