import asyncio
import os
import schedule
import time
import logging
from datetime import datetime, timezone
from db.database import AsyncSessionLocal, engine, Base
from db.seeding import seed_admin
from jobs.ingest_job import run_ingest
from jobs.normalize_job import run_normalize
from jobs.classify_job import run_classify
from jobs.signal_job import run_signal
from jobs.health_check_job import run_health_check
from article.report_job import run_all_reports, create_startup_debug_report
from jobs.trigger_detector_job import run_trigger_check
from jobs.trend_analyze_job import run_trend_analysis
from jobs.alert_manager import run_alert_manager
from jobs.threads_publisher_job import run_threads_publisher
from scripts.backfill_reports import backfill_reports
from jobs.cleanup_job import run_alert_cleanup, run_retention_cleanup, run_db_size_check, enforce_metadata_limits, audit_metadata_sizes, update_system_metric, run_retention_audit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

async def pipeline_full_processing():
    """Unified pipeline from ingest to trigger detection."""
    logger.info("--- Starting Full Processing Pipeline ---")
    async with AsyncSessionLocal() as session:
        # 1. Fetch & Normalize
        logger.info("[INGEST/NORMALIZE]")
        await run_ingest(session)
        await run_normalize(session)
        
        # 2. Classify
        logger.info("[CLASSIFY]")
        await run_classify(session)
        
        # 3. Signal Generation
        logger.info("[SIGNAL]")
        await run_signal(session)

        # 3.1 Trend Analysis (Phase 19)
        logger.info("[TREND ANALYSIS]")
        await run_trend_analysis(session)
        
        # 3.2 Real-time Alerting (Phase 21)
        logger.info("[ALERT CHECK]")
        await run_alert_manager(session)
        
        # 4. Trigger Detection (Event-driven Reports)
        logger.info("[TRIGGER CHECK]")
        await run_trigger_check(session)
    logger.info("--- Pipeline Completed ---")

async def pipeline_health_check():
    logger.info("Running RSS Health Check...")
    async with AsyncSessionLocal() as session:
        await run_health_check(session)

async def daily_reports():
    logger.info("Running Daily Intelligence Reports (Scheduled, English)...")
    async with AsyncSessionLocal() as session:
        await run_all_reports(session, "daily_global", 1, auto_post_threads=True)

async def weekly_reports():
    logger.info("Running Weekly Summary (Scheduled, English)...")
    async with AsyncSessionLocal() as session:
        await run_all_reports(session, "weekly_global", 7, auto_post_threads=True)

async def monthly_reports():
    logger.info("Running Monthly Summary (Scheduled, English)...")
    async with AsyncSessionLocal() as session:
        await run_all_reports(session, "monthly_global", 30, auto_post_threads=True)

def run_monthly_if_first():
    if datetime.now(timezone.utc).day == 1:
        run_async(monthly_reports())

async def run_threads_publisher_wrapper():
    async with AsyncSessionLocal() as session:
        await run_threads_publisher(session)

async def run_alert_cleanup_wrapper():
    async with AsyncSessionLocal() as session:
        await run_alert_cleanup(session)

async def run_retention_cleanup_wrapper():
    async with AsyncSessionLocal() as session:
        await run_retention_cleanup(session)

async def run_db_size_check_wrapper():
    async with AsyncSessionLocal() as session:
        await run_db_size_check(session)

async def run_metadata_audit_wrapper():
    async with AsyncSessionLocal() as session:
        await enforce_metadata_limits(session)
        await audit_metadata_sizes(session)

async def run_retention_audit_wrapper():
    async with AsyncSessionLocal() as session:
        await run_retention_audit(session)


def register_jobs():
    logger.info("Registering job schedules (Threads flow)...")
    # Run the full pipeline every 30 minutes
    schedule.every(30).minutes.do(lambda: run_async(pipeline_full_processing()))

    # Threads publisher polling (every 10 minutes)
    schedule.every(10).minutes.do(lambda: run_async(run_threads_publisher_wrapper()))


    # RSS health check every 6 hours
    schedule.every(6).hours.do(lambda: run_async(pipeline_health_check()))

    # Scheduled Summaries (Safety net / High-level overview)
    schedule.every().day.at("07:00").do(lambda: run_async(daily_reports()))
    schedule.every().monday.at("08:00").do(lambda: run_async(weekly_reports()))
    schedule.every().day.at("09:00").do(run_monthly_if_first)

    # Data Lifecycle & Retention (Cleanup AFTER summaries)
    schedule.every().hour.do(lambda: run_async(run_alert_cleanup_wrapper()))
    schedule.every().day.at("11:00").do(lambda: run_async(run_retention_cleanup_wrapper()))

    # Operational Monitoring
    schedule.every().day.at("00:00").do(lambda: run_async(run_db_size_check_wrapper()))
    schedule.every().day.at("12:00").do(lambda: run_async(run_metadata_audit_wrapper()))
    schedule.every().day.at("23:00").do(lambda: run_async(run_retention_audit_wrapper()))

async def run_startup_checks():
    """Execute immediate tests to verify environment health on startup."""
    logger.info("Triggering IMMEDIATE startup checks...")
    async with AsyncSessionLocal() as session:
        # 0. Backfill Metadata (Phase 14.2 Decoupling/Fix)
        await backfill_reports(session)
        
        # 1. Verify DB writes (Permanently Disabled for Production)
        if False: # Hardcoded False
            await create_startup_debug_report(session)
        # 2. Force an immediate pipeline run
        await pipeline_full_processing()
        # 3. Force an immediate daily report generation
        await run_all_reports(session, "daily_global", 1, auto_post_threads=True)
        
        # 4. Immediate Operational Audit
        await run_db_size_check(session)
        await enforce_metadata_limits(session)
        await audit_metadata_sizes(session)

if __name__ == "__main__":
    async def startup():
        # [Robustness] Ensure all tables exist at startup (Alembic Migration Runner)
        try:
            from db.database import run_migrations
            run_migrations()
            logger.info("Database migration/verification completed (Scheduler).")
        except Exception as e:
            logger.error(f"Database migration output (Scheduler): {e}")

        async with AsyncSessionLocal() as session:
            await seed_admin(session)
            await run_startup_checks()
            await update_system_metric(session, "scheduler_status", "running")

    # 1. Run startup checks
    run_async(startup())
    
    # 2. Register regular schedules
    register_jobs()
    
    # 3. Main scheduler loop
    async def main_loop():
        logger.info("Scheduler loop active. Monitoring heartbeat every 60s.")
        while True:
            schedule.run_pending()
            try:
                async with AsyncSessionLocal() as session:
                    await update_system_metric(session, "scheduler_heartbeat", datetime.now(timezone.utc).isoformat())
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
            await asyncio.sleep(60)

    run_async(main_loop())
