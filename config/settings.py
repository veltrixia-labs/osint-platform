import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from dotenv import load_dotenv

# Load .env WITHOUT overriding variables already set in the environment.
# This was override=True until 2026-10-06. The local .env holds exactly one key,
# DATABASE_URL, which is the PRODUCTION database, so override=True silently
# replaced an explicitly exported DATABASE_URL with production. A
# `DATABASE_URL=<dummy> pytest` run therefore reached production twice on
# 2026-10-06. Nothing depended on .env beating the environment: .env is not
# deployed (.dockerignore), and no other key was in it.
load_dotenv(override=False)

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
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # Stripe Configuration
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    # Per-interval price IDs (May 2026 founding plans)
    stripe_price_id_pro_monthly: str = os.getenv(
        "STRIPE_PRICE_ID_PRO_MONTHLY", "price_1TYffzCc1F7MyO7MLab3Q6zu"
    )
    stripe_price_id_pro_annual: str = os.getenv(
        "STRIPE_PRICE_ID_PRO_ANNUAL", "price_1TYffzCc1F7MyO7MET0aN1Fh"
    )
    stripe_price_id_experts_monthly: str = os.getenv(
        "STRIPE_PRICE_ID_EXPERTS_MONTHLY", "price_1TYfhxCc1F7MyO7MtdZk1pEv"
    )
    stripe_price_id_experts_annual: str = os.getenv(
        "STRIPE_PRICE_ID_EXPERTS_ANNUAL", "price_1TYfhxCc1F7MyO7MaaibN5sL"
    )
    # Legacy aliases (monthly) — prefer STRIPE_PRICE_ID_*_MONTHLY in new deploys
    stripe_price_id_pro: str = os.getenv("STRIPE_PRICE_ID_PRO", "")
    stripe_price_id_experts: str = os.getenv("STRIPE_PRICE_ID_EXPERTS", "")
    domain_url: str = os.getenv("DOMAIN_URL", "http://localhost:8000")

    # Data Retention Policy (Hours/Days)
    alert_retention_hours: int = int(os.getenv("ALERT_RETENTION_HOURS", 24))
    raw_retention_days: int = int(os.getenv("RAW_RETENTION_DAYS", 30))
    # ★ INVARIANT: STALE_ON_ARRIVAL_DAYS must stay BELOW RAW_RETENTION_DAYS.
    #   normalize rejects a new item whose published_at is older than this many days
    #   (processor/normalize.py). Retention deletes raw rows, and with them the dedup memory,
    #   after RAW_RETENTION_DAYS; a feed still serving an entry then re-ingests it with a lag
    #   of at least RAW_RETENTION_DAYS. A threshold below the retention catches every such
    #   re-ingest by construction. At or above it, re-ingested entries pass as "today's news"
    #   (the 2026-10-07 incident, vault audit §12.66-§12.67). normalize REFUSES to apply the
    #   filter, and records that refusal in ingest_rejections, if this invariant is broken.
    #   Lowering RAW_RETENTION_DAYS means lowering this first.
    stale_on_arrival_days: int = int(os.getenv("STALE_ON_ARRIVAL_DAYS", 14))
    ingest_rejection_retention_days: int = int(os.getenv("INGEST_REJECTION_RETENTION_DAYS", 90))
    report_retention_days: int = int(os.getenv("REPORT_RETENTION_DAYS", 30))
    pro_structural_retention_days: int = int(os.getenv("PRO_STRUCTURAL_RETENTION_DAYS", 90))
    retention_dry_run: bool = os.getenv("RETENTION_DRY_RUN", "false").lower() == "true"

    # DB Pressure Monitoring (MB)
    # DB size alarms, compared with pg_database_size in MiB (db/database.py get_db_size_mb: bytes / 1024**2).
    # Basis (vault audit §12.87(e), 2026-10-09): osint-db has a 1 GB disk with Storage Autoscaling DISABLED, so
    # 1 GB is a hard limit. Read conservatively as 10**9 bytes = 953.7 MiB. Disk use also holds ~141 MiB that
    # pg_database_size does not count (WAL: max_wal_size 128 MB, archive_mode on; plus the other databases).
    # P = 953.7 * f - 140.9:  warning at ~70% of disk -> 525,  critical at ~85% of disk -> 670,  full at ~813.
    # The old 400/440 were "~78%/~86% of 512MB", a RAM figure, not disk. WAL growth from a stalled archiver is
    # invisible here; only the Render dashboard's disk figure shows it.
    db_size_warning_mb: int = int(os.getenv("DB_SIZE_WARNING_MB", 525))
    db_size_critical_mb: int = int(os.getenv("DB_SIZE_CRITICAL_MB", 670))
    
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
        if not self.stripe_price_id_pro_monthly:
            raise RuntimeError("STRIPE_PRICE_ID_PRO_MONTHLY is required for Pro subscriptions.")
        if not self.stripe_price_id_pro_annual:
            raise RuntimeError("STRIPE_PRICE_ID_PRO_ANNUAL is required for Pro subscriptions.")
        if not self.stripe_price_id_experts_monthly:
            raise RuntimeError("STRIPE_PRICE_ID_EXPERTS_MONTHLY is required for Expert subscriptions.")
        if not self.stripe_price_id_experts_annual:
            raise RuntimeError("STRIPE_PRICE_ID_EXPERTS_ANNUAL is required for Expert subscriptions.")

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
