import asyncio
import schedule
import time
import logging
from datetime import datetime
from db.database import AsyncSessionLocal
from jobs.ingest_job import run_ingest
from jobs.normalize_job import run_normalize
from jobs.classify_job import run_classify
from jobs.signal_job import run_signal
from jobs.health_check_job import run_health_check
from article.report_job import run_all_reports
from jobs.trigger_detector_job import run_trigger_check
from jobs.trend_analyze_job import run_trend_analysis
from jobs.alert_manager import run_alert_manager
from jobs.threads_publisher_job import run_threads_publisher

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
    if datetime.now().day == 1:
        run_async(monthly_reports())

async def run_threads_publisher_wrapper():
    async with AsyncSessionLocal() as session:
        await run_threads_publisher(session)


def register_jobs():
    logger.info("Registering job schedules (Threads/Substack workflow)...")
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

if __name__ == "__main__":
    register_jobs()
    logger.info("Scheduler started. Running pending tasks continually...")
    while True:
        schedule.run_pending()
        time.sleep(60)
