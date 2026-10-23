import httpx
from typing import Dict, Any, Optional
from app.config import settings

class MubitClient:
    def __init__(self):
        self.api_key = settings.MUBIT_API_KEY
        self.base_url = settings.MUBIT_ANTHROPIC_BASE_URL
        self.model = settings.MUBIT_ANTHROPIC_MODEL

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    async def test_connection(self) -> Dict[str, Any]:
        if not self.is_configured():
            return {
                "active": False,
                "message": "MUBIT_API_KEY environment variable is not configured."
            }
        
        headers = {
            "x-api-key": self.api_key,
            "content-type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Ping"}]
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=payload
                )
                if response.status_code in [200, 201]:
                    return {"active": True, "message": "Successfully authenticated with Mubit."}
                return {
                    "active": False,
                    "message": f"Mubit API error: Http {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {"active": False, "message": f"Connection failed: {str(e)}"}
