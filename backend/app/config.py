import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str = "sqlite:///./evalforge.db"
    
    MUBIT_API_KEY: str = ""
    MUBIT_ANTHROPIC_BASE_URL: str = "https://api.mubit.ai/anthropic"
    MUBIT_ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    
    NEXT_PUBLIC_API_BASE_URL: str = "http://localhost:8000"
    
    MLSTATSOFT_ENABLED: bool = False
    MLSTATSOFT_API_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
