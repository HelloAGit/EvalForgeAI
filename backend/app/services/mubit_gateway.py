"""Claude access through the Mubit gateway using the Anthropic SDK (Anthropic-compatible route).

Credentials come only from backend configuration (``MUBIT_API_KEY``) and are never
returned by any API or written into artefacts. Calls are bounded by a token budget,
an input-size budget, a rate limiter and a bounded retry loop.
"""
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings


class GatewayError(RuntimeError):
    pass


class GatewayNotConfigured(GatewayError):
    pass


class BudgetExceeded(GatewayError):
    pass


@dataclass
class GatewayResponse:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    request_id: Optional[str] = None


class _RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._last = 0.0
        self._calls = deque()

    def acquire(self, min_interval: float, max_per_hour: int, sleep=time.sleep, now=time.monotonic):
        with self._lock:
            t = now()
            while self._calls and t - self._calls[0] > 3600:
                self._calls.popleft()
            if len(self._calls) >= max_per_hour:
                raise BudgetExceeded(f"Hourly Mubit call budget ({max_per_hour}) exhausted.")
            wait = self._last + min_interval - t
            if wait > 0:
                sleep(wait)
                t = now()
            self._last = t
            self._calls.append(t)


_limiter = _RateLimiter()


class MubitGateway:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None, client: Any = None, limiter: Optional[_RateLimiter] = None,
                 sleep=time.sleep):
        self.api_key = settings.MUBIT_API_KEY if api_key is None else api_key
        self.base_url = base_url or settings.MUBIT_ANTHROPIC_BASE_URL
        self.model = model or settings.MUBIT_ANTHROPIC_MODEL
        self._client = client
        self._limiter = limiter or _limiter
        self._sleep = sleep

    def is_configured(self) -> bool:
        return bool(self._client is not None or (self.api_key and self.api_key.strip()))

    def _sdk(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url,
                                               timeout=settings.MUBIT_TIMEOUT_SECONDS, max_retries=0)
        return self._client

    def complete(self, system: str, user: str, max_tokens: Optional[int] = None,
                 temperature: float = 0.0) -> GatewayResponse:
        if not self.is_configured():
            raise GatewayNotConfigured("MUBIT_API_KEY is not configured.")
        if len(system) + len(user) > settings.MUBIT_MAX_INPUT_CHARS:
            raise BudgetExceeded(f"Input of {len(system) + len(user)} characters exceeds the "
                                 f"MUBIT_MAX_INPUT_CHARS budget ({settings.MUBIT_MAX_INPUT_CHARS}).")
        max_tokens = min(max_tokens or settings.MUBIT_MAX_TOKENS, settings.MUBIT_MAX_TOKENS)
        last_exc: Optional[Exception] = None
        for attempt in range(settings.MUBIT_MAX_RETRIES + 1):
            self._limiter.acquire(settings.MUBIT_MIN_INTERVAL_SECONDS, settings.MUBIT_MAX_CALLS_PER_HOUR)
            try:
                msg = self._sdk().messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature,
                                                  system=system, messages=[{"role": "user", "content": user}])
                text = "".join(getattr(b, "text", "") for b in msg.content)
                usage = getattr(msg, "usage", None)
                return GatewayResponse(text, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
                                       getattr(msg, "id", None))
            except Exception as exc:  # SDK raises typed errors; retry only transient ones
                last_exc = exc
                status = getattr(exc, "status_code", None)
                transient = status is None or status == 429 or status >= 500
                if not transient or attempt >= settings.MUBIT_MAX_RETRIES:
                    break
                self._sleep(min(2 ** attempt, 30))
        raise GatewayError(f"Mubit request failed: {type(last_exc).__name__}") from last_exc
