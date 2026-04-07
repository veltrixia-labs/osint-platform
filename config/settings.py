import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from dotenv import load_dotenv

# Force-load .env at the very beginning
load_dotenv(override=True)

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
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # Stripe Configuration
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_price_id_pro: str = os.getenv("STRIPE_PRICE_ID_PRO", "")
    stripe_price_id_experts: str = os.getenv("STRIPE_PRICE_ID_EXPERTS", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    domain_url: str = os.getenv("DOMAIN_URL", "http://localhost:8000")

    # Data Retention Policy (Hours/Days)
    alert_retention_hours: int = int(os.getenv("ALERT_RETENTION_HOURS", 24))
    raw_retention_days: int = int(os.getenv("RAW_RETENTION_DAYS", 30))
    report_retention_days: int = int(os.getenv("REPORT_RETENTION_DAYS", 30))
    retention_dry_run: bool = os.getenv("RETENTION_DRY_RUN", "false").lower() == "true"

    # DB Pressure Monitoring (MB)
    db_size_warning_mb: int = int(os.getenv("DB_SIZE_WARNING_MB", 400)) # ~78% of 512MB
    db_size_critical_mb: int = int(os.getenv("DB_SIZE_CRITICAL_MB", 440)) # ~86% of 512MB
    
    # Metadata Safeguards
    metadata_max_size_chars: int = int(os.getenv("METADATA_MAX_SIZE_CHARS", 50000))
    
    # External Monitoring
    monitoring_webhook_url: Optional[str] = os.getenv("MONITORING_WEBHOOK_URL")

    def validate_stripe(self):
        """Stripe の必須設定が欠落していないか検証します。"""
        # 本番環境または決済機能を有効にする場合は、これらは必須です。
        if not self.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is required for payment features.")
        if not self.stripe_webhook_secret:
            raise RuntimeError("STRIPE_WEBHOOK_SECRET is required for secure webhook processing.")
        if not self.stripe_price_id_pro:
            raise RuntimeError("STRIPE_PRICE_ID_PRO is required for Pro subscriptions.")
        if not self.stripe_price_id_experts:
            raise RuntimeError("STRIPE_PRICE_ID_EXPERTS is required for Experts subscriptions.")

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding='utf-8', 
        extra='ignore',
        case_sensitive=False
    )

settings = Settings()
# Note: In production, we log missing keys but don't crash on startup 
# to allow diagnostic endpoints like /api/version to work.
try:
    settings.validate_stripe()
except RuntimeError as e:
    import logging
    logging.getLogger(__name__).warning(f"STRIPE CONFIG INCOMPLETE: {e}")
