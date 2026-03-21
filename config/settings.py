import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///osint_platform.db")

    def get_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    
    # Stripe Configuration
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_price_id_pro: str = os.getenv("STRIPE_PRICE_ID_PRO", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    domain_url: str = os.getenv("DOMAIN_URL", "http://localhost:8000")

    def validate_stripe(self):
        """Stripe の必須設定が欠落していないか検証します。"""
        # 本番環境または決済機能を有効にする場合は、これらは必須です。
        if not self.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is required for payment features.")
        if not self.stripe_webhook_secret:
            raise RuntimeError("STRIPE_WEBHOOK_SECRET is required for secure webhook processing.")
        if not self.stripe_price_id_pro:
            raise RuntimeError("STRIPE_PRICE_ID_PRO is required for Pro subscriptions.")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')

settings = Settings()
settings.validate_stripe()
