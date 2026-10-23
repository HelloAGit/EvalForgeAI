from typing import Dict, Any
from app.config import settings

class MLStatSoftAdapter:
    def __init__(self):
        self.enabled = settings.MLSTATSOFT_ENABLED
        self.api_key = settings.MLSTATSOFT_API_KEY

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key)

    def delegate_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "delegated": False,
                "reason": "MLStatSoft integration disabled or unconfigured. Falling back to native SciPy/Statsmodels engine."
            }
        # Placeholder adapter hook awaiting published API specifications from mlstatsoft.com
        return {"delegated": True, "status": "NotImplemented"}
