import asyncio
import os
import schedule
import logging
from datetime import datetime, timezone
from db.database import AsyncSessionLocal
from db.seeding import seed_admin
from jobs.ingest_job import run_ingest
from processor.normalize import run_normalize
from processor.classify import run_classify
from jobs.signal_job import run_signal
from jobs.health_check_job import run_health_check
from jobs.report_orchestrator import run_all_reports
from jobs.trigger_detector_job import run_trigger_check
from jobs.trend_analyze_job import run_trend_analysis
from jobs.alert_manager import run_alert_manager
from jobs.threads_publisher_job import run_threads_publisher
from jobs.learning_loop import run_learning_job
from jobs.cleanup_job import (
    run_alert_cleanup, run_retention_cleanup, run_db_size_check, 
    enforce_metadata_limits, audit_metadata_sizes, update_system_metric, 
    run_retention_audit, run_trend_cleanup, run_visual_cleanup
)
from jobs.entity_lifecycle import run_entity_lifecycle  # [v10.21]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Safe Task Execution & Concurrency Guards ---

_running_tasks = set()

async def safe_run(name, coro_func, *args, **kwargs):
    """
    Executes a coroutine with a concurrency guard and exception logging.
    Used as an async task target.
    """
    if name in _running_tasks:
        logger.warning(f"Task '{name}' is already running. Skipping this cycle.")
        return
    
    _running_tasks.add(name)
    try:
        logger.info(f"Starting scheduled task: {name}")
        await coro_func(*args, **kwargs)
        logger.info(f"Finished scheduled task: {name}")
    except Exception as e:
        logger.exception(f"FATAL: Task '{name}' failed with exception: {e}")
    finally:
        _running_tasks.remove(name)

def schedule_async(name, coro_func, *args, **kwargs):
    """
    Bridge synchronous schedule callback to the active async event loop.
    Fires tasks using create_task to avoid blocking or re-entering the loop.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(safe_run(name, coro_func, *args, **kwargs))
    except RuntimeError:
        logger.error(f"Cannot schedule task '{name}': No running event loop.")

# --- Jobs & Wrappers ---

async def pipeline_full_processing():
    """Unified pipeline from ingest to trigger detection."""
    if os.getenv("SCHEDULER_PAUSED") == "true":
        logger.warning("SCHEDULER IS PAUSED (via SCHEDULER_PAUSED env var). Skipping pipeline.")
        return

    logger.info("--- Starting Full Processing Pipeline ---")
    try:
        async with AsyncSessionLocal() as session:
            logger.info("[INGEST/NORMALIZE]")
            await run_ingest(session)
            await run_normalize(session)
            
            logger.info("[CLASSIFY]")
            await run_classify(session)
            
            logger.info("[SIGNAL]")
            await run_signal(session)

            logger.info("[TREND ANALYSIS]")
            await run_trend_analysis(session)
            
            logger.info("[ALERT CHECK]")
            await run_alert_manager(session)
            
            logger.info("[TRIGGER CHECK]")
            await run_trigger_check(session)
            
            from jobs.cleanup_job import update_system_metric
            await update_system_metric(session, "scheduler_last_full_run", datetime.now(timezone.utc).isoformat())
            
        logger.info("--- Pipeline Completed Successfully ---")
    except Exception as e:
        err_msg = str(e)
        if "DiskFullError" in err_msg or "No space left on device" in err_msg:
            logger.critical(f"FATAL STORAGE ERROR during pipeline: {e}. EMERGENCY PAUSE TRIGGERED.")
        elif "PendingRollbackError" in err_msg:
            logger.warning(f"Database session in pending rollback state: {e}. Skipping this cycle.")
        else:
            logger.error(f"Error in processing pipeline: {e}")
            raise

async def pipeline_health_check_wrapper():
    async with AsyncSessionLocal() as session:
        await run_health_check(session)

async def daily_reports_wrapper():
    async with AsyncSessionLocal() as session:
        await run_all_reports(session, "daily", 1, auto_post_threads=True)

async def weekly_reports_wrapper():
    async with AsyncSessionLocal() as session:
        await run_all_reports(session, "weekly", 7, auto_post_threads=True)

async def monthly_reports_wrapper():
    if datetime.now(timezone.utc).day == 1:
        async with AsyncSessionLocal() as session:
            await run_all_reports(session, "monthly", 30, auto_post_threads=True)

async def run_threads_publisher_wrapper():
    async with AsyncSessionLocal() as session:
        await run_threads_publisher(session)

async def run_learning_wrapper():
    await run_learning_job()

async def run_cleanup_bundle():
    """Bundle of hourly/daily cleanups to ensure they run under one concurrency guard name."""
    async with AsyncSessionLocal() as session:
        logger.info("[CLEANUP] Start Alert Cleanup")
        await run_alert_cleanup(session)
        logger.info("[CLEANUP] Start Trend Cleanup")
        await run_trend_cleanup(session)
        
        # Daily specific checks (if we were more granular, we'd split these, 
        # but for now running hourly is safe and ensures space is reclaimed).
        logger.info("[CLEANUP] Metadata limit enforcement")
        await enforce_metadata_limits(session)

async def run_ops_monitoring():
    async with AsyncSessionLocal() as session:
        await run_db_size_check(session)
        await audit_metadata_sizes(session)
        await run_retention_audit(session)
        await run_retention_cleanup(session) # Full retention cleanup
    
    # Visual Asset Cleanup (Configurable via ENV)
    # Defaulting to dry_run=True or archive_only=True during initial rollout for safety
    dry_run = os.getenv("CLEANUP_DRY_RUN", "true").lower() == "true"
    archive_only = os.getenv("CLEANUP_ARCHIVE_ONLY", "true").lower() == "true"
    retention = int(os.getenv("CLEANUP_RETENTION_DAYS", "14"))
    
    await run_visual_cleanup(dry_run=dry_run, archive_only=archive_only, retention=retention)
    
    # [v10.21] Entity Lifecycle: recalculate scores and prune obsolete tactical nodes
    await run_entity_lifecycle(db_pressure_critical=False)

def register_jobs():
    logger.info("Registering job schedules (Async Native Mapping)...")
    
    # Core Pipeline
    schedule.every(5).minutes.do(schedule_async, "pipeline", pipeline_full_processing)

    # Threads publisher (Polling)
    schedule.every(10).minutes.do(schedule_async, "threads_publisher", run_threads_publisher_wrapper)

    # RSS health check
    schedule.every(6).hours.do(schedule_async, "health_check", pipeline_health_check_wrapper)

    # Scheduled Reports
    schedule.every().day.at("07:00").do(schedule_async, "daily_report", daily_reports_wrapper)
    schedule.every().monday.at("08:00").do(schedule_async, "weekly_report", weekly_reports_wrapper)
    schedule.every().day.at("09:00").do(schedule_async, "monthly_report", monthly_reports_wrapper)

    # Cleanup & Retention (Concurrency guarded by "cleanup")
    schedule.every().hour.do(schedule_async, "cleanup", run_cleanup_bundle)

    # Operational Monitoring
    schedule.every().day.at("00:00").do(schedule_async, "ops_monitoring", run_ops_monitoring)

    # [v10.21] Entity Lifecycle Management (Strategic Score + Pruning @ 03:00 daily)
    schedule.every().day.at("03:00").do(schedule_async, "entity_lifecycle", run_entity_lifecycle)

    # Phase 4: Self-Learning Feedback Loop (Daily at 02:00)
    schedule.every().day.at("02:00").do(schedule_async, "learning_loop", run_learning_wrapper)

async def run_startup_checks():
    """Execute immediate tests to verify environment health on startup."""
    logger.info("Triggering IMMEDIATE startup checks...")
    async with AsyncSessionLocal() as session:
        # Force an immediate pipeline run
        await pipeline_full_processing()
        
        # Immediate Operational Audit
        await run_db_size_check(session)
        await enforce_metadata_limits(session)
        await audit_metadata_sizes(session)

async def main():
    logger.info("--- OSINT SCHEDULER STARTUP ---")
    logger.info("SCHEDULER_V2_ACTIVE")
    
    # 1. Database Migrations & Seeding
    try:
        from db.database import run_migrations
        run_migrations()
        logger.info("Database migration/verification completed.")
    except Exception as e:
        logger.error(f"Database migration failure: {e}")

    async with AsyncSessionLocal() as session:
        await seed_admin(session)
        await update_system_metric(session, "scheduler_status", "starting")

    # 2. Immediate Startup Pipeline (Resilient)
    try:
        await run_startup_checks()
    except Exception as startup_e:
        logger.error(f"[SELF-HEALING] Startup checks failed (Likely API/RateLimit): {startup_e}")
        logger.info("[SELF-HEALING] Proceeding to background schedule loop anyway.")

    # 3. Register Regular Jobs
    register_jobs()

    # 4. Main Scheduler Loop
    logger.info("Scheduler loop active. Monitoring heartbeat every 60s.")
    async with AsyncSessionLocal() as session:
        await update_system_metric(session, "scheduler_status", "running")

    while True:
        if os.getenv("SCHEDULER_PAUSED") == "true":
            await asyncio.sleep(60)
            continue

        schedule.run_pending()
        
        try:
            async with AsyncSessionLocal() as session:
                await update_system_metric(session, "scheduler_heartbeat", datetime.now(timezone.utc).isoformat())
        except Exception as e:
            err_msg = str(e).lower()
            if "diskfullerror" in err_msg or "no space left" in err_msg:
                logger.critical(f"HEARTBEAT FAILED: DB IS FULL. {e}")
                await asyncio.sleep(300)
            else:
                logger.error(f"Heartbeat failed: {e}")
        
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
