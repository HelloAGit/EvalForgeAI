from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str = "sqlite:///./evalforge.db"
    AUTO_MIGRATE: bool = True

    # --- Authentication / authorisation -------------------------------------
    # Comma separated "token:user_id:role" entries (role = admin | user).
    EVALFORGE_API_KEYS: str = ""
    # Only honoured when APP_ENV == "development".
    AUTH_DISABLED: bool = False
    CORS_ORIGINS: str = "http://localhost:3000"

    # --- Mubit / Claude (backend-only credentials, never sent to the browser) --
    MUBIT_API_KEY: str = ""
    MUBIT_ANTHROPIC_BASE_URL: str = "https://api.mubit.ai/anthropic"
    MUBIT_ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    MUBIT_MAX_TOKENS: int = 4096
    MUBIT_MAX_INPUT_CHARS: int = 60000
    MUBIT_MAX_RETRIES: int = 2
    MUBIT_TIMEOUT_SECONDS: float = 60.0
    MUBIT_MIN_INTERVAL_SECONDS: float = 1.0
    MUBIT_MAX_CALLS_PER_HOUR: int = 30

    NEXT_PUBLIC_API_BASE_URL: str = "http://localhost:8000"

    MLSTATSOFT_ENABLED: bool = False
    MLSTATSOFT_API_KEY: str = ""

    # --- Dashboard ------------------------------------------------------------
    QUALITY_INDEX_WEIGHTS_JSON: str = ""  # optional {"metric_key": weight} override
    QI_MIN_COVERAGE: float = 0.5
    MIN_OBSERVATIONS: int = 3
    REGRESSION_DROP_THRESHOLD: float = 0.05
    SSE_POLL_SECONDS: float = 1.0
    SSE_HEARTBEAT_SECONDS: float = 15.0
    SSE_MAX_DURATION_SECONDS: float = 300.0
    SSE_MAX_CATCHUP_EVENTS: int = 500

    # --- Scheduling / worker --------------------------------------------------
    SCHEDULER_MAX_RUNS_PER_DAY: int = 24
    WORKER_POLL_SECONDS: float = 2.0
    WORKER_LEASE_SECONDS: int = 600
    WORKER_INLINE: bool = False

    # --- Artefact storage -----------------------------------------------------
    ARTIFACT_DIR: str = "./data/artifacts"
    MAX_ARTIFACT_BYTES: int = 1024 * 1024 * 1024

    # --- Video ----------------------------------------------------------------
    VIDEO_WIDTH: int = 1920
    VIDEO_HEIGHT: int = 1080
    VIDEO_FPS: int = 30
    VIDEO_MAX_DURATION_SECONDS: int = 300
    VIDEO_RENDER_TIMEOUT_SECONDS: int = 1800
    VIDEO_MAX_ATTEMPTS: int = 2
    VIDEO_MAX_ACTIVE_PER_USER: int = 3
    FFMPEG_PATH: str = ""  # empty = bundled imageio-ffmpeg binary
    TTS_PROVIDER: str = "none"  # none | http
    TTS_ENDPOINT_URL: str = ""
    TTS_API_KEY: str = ""
    TTS_VOICES: str = "default"  # comma separated voice ids offered by the configured provider
    TTS_TIMEOUT_SECONDS: float = 60.0
    TTS_MAX_CHARS_PER_SCENE: int = 1500

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
