import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    def get_database_url(self) -> str:
        url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/osint_platform")
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def database_url(self) -> str:
        return self.get_database_url()

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    openai_api_key: str = ""
    gemini_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')

settings = Settings()
