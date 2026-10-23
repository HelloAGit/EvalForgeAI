import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str = "sqlite:///./evalforge.db"
    
    MUBIT_API_KEY: str = "mbt_mw-app_157a543dbd714568_8ef71cb4b4924cc0bc3a25c70893d9a2208113bca198467cb57969b615715bf4"
    MUBIT_ANTHROPIC_BASE_URL: str = "https://api.mubit.ai/anthropic"
    MUBIT_ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    
    NEXT_PUBLIC_API_BASE_URL: str = "http://localhost:8000"
    
    MLSTATSOFT_ENABLED: bool = False
    MLSTATSOFT_API_KEY: str = "msk_d3e4a57c4d8d7875ece0507b99b045d65ffc0772e612d57ee22a769df5ffd91d"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
