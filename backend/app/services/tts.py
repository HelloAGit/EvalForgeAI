"""Pluggable text-to-speech providers. A provider turns text into 16-bit PCM WAV bytes.

The Claude Messages API does not produce audio, so narration always goes through a separate
provider configured with TTS_PROVIDER. ``none`` (default) disables narrated mode.
"""
import io
import json
import math
import struct
import wave
from abc import ABC, abstractmethod
from typing import List
from urllib import request as urlrequest

from app.config import settings


class TTSError(RuntimeError):
    pass


class TTSProvider(ABC):
    name = "abstract"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def voices(self) -> List[str]: ...

    @abstractmethod
    def synthesize(self, text: str, voice: str) -> bytes:
        """Return WAV (RIFF, 16-bit PCM) bytes."""


class NoTTS(TTSProvider):
    name = "none"

    def available(self) -> bool:
        return False

    def voices(self) -> List[str]:
        return []

    def synthesize(self, text: str, voice: str) -> bytes:
        raise TTSError("No TTS provider is configured (set TTS_PROVIDER).")


class HttpTTS(TTSProvider):
    """Generic HTTP provider: POST {"text","voice"} -> audio/wav body. Adapt a vendor API behind a small proxy
    or subclass this for vendor-specific payloads. Credentials come from TTS_API_KEY (backend only)."""
    name = "http"

    def available(self) -> bool:
        return bool(settings.TTS_ENDPOINT_URL)

    def voices(self) -> List[str]:
        return [v.strip() for v in settings.TTS_VOICES.split(",") if v.strip()]

    def synthesize(self, text: str, voice: str) -> bytes:
        if not self.available():
            raise TTSError("TTS_ENDPOINT_URL is not configured.")
        if not settings.TTS_ENDPOINT_URL.startswith(("https://", "http://")):
            raise TTSError("TTS_ENDPOINT_URL must be an http(s) URL.")
        headers = {"Content-Type": "application/json", "Accept": "audio/wav"}
        if settings.TTS_API_KEY:
            headers["Authorization"] = "Bearer " + settings.TTS_API_KEY
        req = urlrequest.Request(settings.TTS_ENDPOINT_URL, data=json.dumps({"text": text, "voice": voice}).encode(),
                                 headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=settings.TTS_TIMEOUT_SECONDS) as resp:  # noqa: S310 (operator-configured URL)
                data = resp.read(64 * 1024 * 1024)
        except Exception as exc:
            raise TTSError(f"TTS request failed: {type(exc).__name__}") from exc
        wav_info(data)  # validates
        return data


class MockTTS(TTSProvider):
    """Deterministic offline provider used by tests: a quiet tone whose length scales with the text."""
    name = "mock"

    def __init__(self, voices=("mock-voice",), seconds_per_char=0.04, rate=16000):
        self._voices, self.spc, self.rate = list(voices), seconds_per_char, rate
        self.calls: List[tuple] = []

    def available(self) -> bool:
        return True

    def voices(self) -> List[str]:
        return self._voices

    def synthesize(self, text: str, voice: str) -> bytes:
        self.calls.append((text, voice))
        n = int(self.rate * max(0.3, len(text) * self.spc))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"".join(struct.pack("<h", int(1500 * math.sin(2 * math.pi * 220 * i / self.rate))) for i in range(n)))
        return buf.getvalue()


def wav_info(data: bytes) -> dict:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2:
                raise TTSError("TTS audio must be 16-bit PCM WAV.")
            return {"channels": w.getnchannels(), "rate": w.getframerate(), "frames": w.getnframes(),
                    "seconds": w.getnframes() / float(w.getframerate())}
    except (wave.Error, EOFError) as exc:
        raise TTSError(f"TTS provider did not return valid WAV audio: {exc}") from exc


def get_tts() -> TTSProvider:
    return HttpTTS() if settings.TTS_PROVIDER == "http" else NoTTS()
