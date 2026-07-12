import asyncio
import gc
import logging
import os
from datetime import datetime, timezone

import schedule

from db.database import AsyncSessionLocal
from db.seeding import seed_admin
from jobs._memutil import current_rss_mb, peak_rss_mb
from jobs.ingest_job import run_ingest
from processor.normalize import run_normalize
from jobs.signal_job import run_signal
from jobs.health_check_job import run_health_check
from jobs.report_orchestrator import run_all_reports
from jobs.trigger_detector_job import run_trigger_check
from jobs.trend_analyze_job import run_trend_analysis
from jobs.alert_manager import run_alert_manager
from jobs.monthly_trend_worker import run_monthly_trend_worker, prune_monthly_trends
from jobs.threads_publisher_job import run_threads_publisher
from jobs.cleanup_job import (
    run_alert_cleanup, run_retention_cleanup, run_db_size_check,
    enforce_metadata_limits, audit_metadata_sizes, update_system_metric,
    run_retention_audit, run_trend_cleanup, run_visual_cleanup,
    run_pro_structural_retention_wrapper,
)
from jobs.entity_lifecycle import run_entity_lifecycle  # [v10.21]
from processor.impact_discovery import ImpactDiscoveryEngine # [v12.0]
from jobs.external_data_sync import run_daily_external_data_sync_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Safe Task Execution & Concurrency Guards ---

_running_tasks = set()
# NOTE: _heavy_work_lock / _heavy_db_lock / _external_data_sync_lock are three
#       INTENTIONALLY SEPARATE locks. The daily external-sync tail (the 6-domain
#       pro compile in external_data_sync.py) runs inside _external_data_sync_lock
#       and additionally grabs _heavy_work_lock — safe under the EDS→HW order. If
#       you ever merge these into one lock, that wrap re-acquires an already-held
#       lock (EDS) and self-deadlocks: REMOVE the wrap in external_data_sync.py
#       when merging. (Mirror of the NOTE at that wrap site.)
# Serialize heavy memory jobs (full pipeline vs discovery scout) to avoid OOM spikes.
_heavy_work_lock = asyncio.Lock()
# Shared mutex for the memory-heavy BATCH jobs (monthly_trend, cleanup, ops,
# daily/weekly/monthly reports). Their cron times overlap (e.g. cleanup is hourly
# and fires at 09:00 alongside monthly_report); this guarantees only one runs at a
# time so their full-table scans never stack and blow the 512MB ceiling.
_heavy_db_lock = asyncio.Lock()
# Macro API sync runs separately so the 5-minute OSINT pipeline is not blocked.
_external_data_sync_lock = asyncio.Lock()

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

    async with _heavy_work_lock:
        await _pipeline_full_processing_locked()


async def _pipeline_full_processing_locked():
    logger.info("--- Starting Full Processing Pipeline ---")
    try:
        async with AsyncSessionLocal() as session:
            logger.info("[INGEST/NORMALIZE]")
            await run_ingest(session)
            await run_normalize(session)

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

            # Clear the ORM identity map before the session closes, then force a
            # GC pass so each 5-min cycle returns its working set (signal's
            # per-topic ORM loads + clustering buffers) to the OS instead of
            # letting it accrue toward the 512MB ceiling.
            session.expire_all()

        gc.collect()
        logger.info(f"[MEM] pipeline cycle end rss={current_rss_mb():.0f}MB peak_rss={peak_rss_mb():.0f}MB")
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
    async with _heavy_db_lock:
        async with AsyncSessionLocal() as session:
            await run_all_reports(session, "daily", 1, auto_post_threads=True)
    gc.collect()

async def weekly_reports_wrapper():
    async with _heavy_db_lock:
        async with AsyncSessionLocal() as session:
            await run_all_reports(session, "weekly", 7, auto_post_threads=True)
    gc.collect()

async def monthly_reports_wrapper():
    if datetime.now(timezone.utc).day != 1:
        return
    async with _heavy_db_lock:
        async with AsyncSessionLocal() as session:
            await run_all_reports(session, "monthly", 30, auto_post_threads=True)
    gc.collect()

async def monthly_trend_wrapper():
    # Spatial subsystem is live (quarantine lifted): the monthly-trend builder
    # routes spikes through SpatialPhysicsEngine + the geo/omni-spatial worker.
    now = datetime.now(timezone.utc)
    async with _heavy_db_lock:  # never overlap cleanup / reports / ops (OOM avoidance)
        async with AsyncSessionLocal() as session:
            # On the 1st, lock in the just-completed previous month (idempotent).
            if now.day == 1:
                await run_monthly_trend_worker(session)
            # ALWAYS refresh the IN-PROGRESS current month so the dashboard streams
            # live data instead of stalling on the last completed month. Force-
            # rebuild to absorb new spikes.
            await run_monthly_trend_worker(session, year=now.year, month=now.month, force=True)
            # Enforce the 3-month rolling window: drop archives older than current+2.
            await prune_monthly_trends(session, now=now)
            session.expire_all()
    gc.collect()

async def run_threads_publisher_wrapper():
    async with AsyncSessionLocal() as session:
        await run_threads_publisher(session)

async def run_discovery_scout_wrapper():
    """Autonomous scout for AI discovery."""
    async with _heavy_work_lock:
        await ImpactDiscoveryEngine.run_discovery_scout()

async def run_cleanup_bundle():
    """Bundle of hourly/daily cleanups under the shared heavy-DB mutex so they
    never run concurrently with monthly_trend / reports / ops (OOM avoidance).
    Preserves the cleanup-first ordering: alert → trend → metadata enforcement."""
    async with _heavy_db_lock:
        async with AsyncSessionLocal() as session:
            logger.info("[CLEANUP] Start Alert Cleanup")
            await run_alert_cleanup(session)
            logger.info("[CLEANUP] Start Trend Cleanup")
            await run_trend_cleanup(session)

            # Daily specific checks (if we were more granular, we'd split these,
            # but for now running hourly is safe and ensures space is reclaimed).
            logger.info("[CLEANUP] Metadata limit enforcement")
            await enforce_metadata_limits(session)
            session.expire_all()
    gc.collect()

async def run_ops_monitoring():
    async with _heavy_db_lock:
        async with AsyncSessionLocal() as session:
            await run_db_size_check(session)
            await audit_metadata_sizes(session)
            await run_retention_audit(session)
            await run_retention_cleanup(session) # Full retention cleanup
            session.expire_all()

        # Visual Asset Cleanup (Configurable via ENV) — uses the streamed
        # build_reference_map; kept inside the mutex so it cannot overlap cleanup.
        # Defaulting to dry_run=True or archive_only=True during initial rollout.
        dry_run = os.getenv("CLEANUP_DRY_RUN", "true").lower() == "true"
        archive_only = os.getenv("CLEANUP_ARCHIVE_ONLY", "true").lower() == "true"
        retention = int(os.getenv("CLEANUP_RETENTION_DAYS", "14"))
        await run_visual_cleanup(dry_run=dry_run, archive_only=archive_only, retention=retention)
    gc.collect()
    
    # [v10.21] Entity Lifecycle: recalculate scores and prune obsolete tactical nodes
    await run_entity_lifecycle(db_pressure_critical=False)

async def pro_automation_wrapper():
    """Rule-based Pro Structural Brief compile (6 domains, no LLM)."""
    from jobs.pro_realtime_stream import run_continuous_pro_intelligence_stream

    # Serialize under the shared heavy-work mutex (same lock as the full pipeline
    # and discovery scout) so the structural-brief compile can never run
    # concurrently with the 5-min pipeline and stack memory past 512MB.
    async with _heavy_work_lock:
        return await run_continuous_pro_intelligence_stream()


async def run_cftc_sync_wrapper():
    """Weekly Commitments of Traders ingestion (Socrata, no API key)."""
    if os.getenv("SCHEDULER_PAUSED") == "true":
        logger.warning("SCHEDULER_PAUSED — skipping CFTC sync.")
        return
    from jobs.cftc_sync_job import run_cftc_sync

    summary = await run_cftc_sync(weeks=int(os.getenv("CFTC_SYNC_WEEKS", "52")))
    logger.info("CFTC sync summary: %s", summary)


async def run_omni_spatial_worker_wrapper():
    """Phase 7.2: Translate recent AlertLog rows into spatial contagion graphs."""
    if os.getenv("SCHEDULER_PAUSED") == "true":
        logger.warning("SCHEDULER_PAUSED — skipping omni spatial worker.")
        return
    from jobs.omni_spatial_worker import run_omni_spatial_worker

    # Serialize against the full pipeline / discovery scout (shared heavy-work
    # mutex) so the spatial contagion build — which fires on the SAME 5-min tick
    # as the pipeline — can no longer stack on top of it and blow the 512MB
    # ceiling (the daily ~14:30 multi-job OOM).
    async with _heavy_work_lock:
        summary = await run_omni_spatial_worker()
    logger.info("Omni spatial worker summary: %s", summary)


async def run_sanctions_sync_wrapper():
    """Daily OpenSanctions bulk dump + PageRank recompute."""
    if os.getenv("SCHEDULER_PAUSED") == "true":
        logger.warning("SCHEDULER_PAUSED — skipping sanctions sync.")
        return
    from jobs.sanctions_sync_job import run_sanctions_sync

    summary = await run_sanctions_sync()
    logger.info("Sanctions sync summary: %s", summary)


async def run_external_data_sync_wrapper():
    """
    Phase 0: Daily macro sync (FRED, BLS, World Bank, Comtrade, BEA, Census).
    Sequential steps with inter-step delay; isolated from the OSINT ingest pipeline.
    Schedule host should run in UTC (see EXTERNAL_DATA_SYNC_UTC_TIME).
    """
    if os.getenv("SCHEDULER_PAUSED") == "true":
        logger.warning("SCHEDULER_PAUSED — skipping external data sync.")
        return
    async with _external_data_sync_lock:
        await run_daily_external_data_sync_pipeline()


def register_jobs():
    logger.info("Registering job schedules (Async Native Mapping)...")
    
    # Core Pipeline
    schedule.every(5).minutes.do(schedule_async, "pipeline", pipeline_full_processing)

    # Phase 7.2: RSS → physics-based spatial contagion (Omni monitor tables)
    schedule.every(5).minutes.do(
        schedule_async,
        "omni_spatial",
        run_omni_spatial_worker_wrapper,
    )
    logger.info("Registered omni_spatial every 5 minutes (spatial_nodes / spatial_edges / contagion_history).")

    # [v12.0] Autonomous Discovery Scout (High Frequency)
    schedule.every(1).minutes.do(schedule_async, "discovery_scout", run_discovery_scout_wrapper)

    # Threads publisher (Polling)
    schedule.every(10).minutes.do(schedule_async, "threads_publisher", run_threads_publisher_wrapper)

    # RSS health check
    schedule.every(6).hours.do(schedule_async, "health_check", pipeline_health_check_wrapper)

    # Scheduled Reports
    schedule.every().day.at("07:00").do(schedule_async, "daily_report", daily_reports_wrapper)
    schedule.every().monday.at("08:00").do(schedule_async, "weekly_report", weekly_reports_wrapper)
    schedule.every().day.at("09:00").do(schedule_async, "monthly_report", monthly_reports_wrapper)
    # Hourly (at :30, off the top-of-hour cleanup) so the dashboard reflects "today"
    # intraday. The builder is streamed + idempotent (force-rebuild current month),
    # and runs under _heavy_db_lock so it never stacks with cleanup on 512MB.
    schedule.every().hour.at(":30").do(schedule_async, "monthly_trend", monthly_trend_wrapper)

    # Cleanup & Retention (Concurrency guarded by "cleanup")
    schedule.every().hour.do(schedule_async, "cleanup", run_cleanup_bundle)

    # Operational Monitoring
    schedule.every().day.at("00:00").do(schedule_async, "ops_monitoring", run_ops_monitoring)

    # Phase 0: External macro data (FRED/BLS/WB/Comtrade/BEA/Census) — once daily, sequential + jitter inside job
    external_sync_time = os.getenv("EXTERNAL_DATA_SYNC_UTC_TIME", "00:05")
    schedule.every().day.at(external_sync_time).do(
        schedule_async,
        "external_data_sync",
        run_external_data_sync_wrapper,
    )
    logger.info(
        "Registered external_data_sync daily at %s (host local time; use TZ=UTC). "
        "Inter-step delay: EXTERNAL_SYNC_INTER_STEP_SECONDS (default 1200).",
        external_sync_time,
    )

    # [v10.21] Entity Lifecycle Management (Strategic Score + Pruning @ 03:00 daily)
    schedule.every().day.at("03:00").do(schedule_async, "entity_lifecycle", run_entity_lifecycle)

    # Phase 7: Pro Structural Brief Automation (continuous INSERT stream)
    pro_interval_min = int(os.getenv("PRO_AUTOMATION_INTERVAL_MINUTES", "30"))
    if pro_interval_min > 0:
        schedule.every(pro_interval_min).minutes.do(
            schedule_async, "pro_automation", pro_automation_wrapper
        )
        logger.info(
            "Registered pro_automation every %s minutes (continuous structural brief INSERT stream).",
            pro_interval_min,
        )
    else:
        pro_interval_h = int(os.getenv("PRO_AUTOMATION_INTERVAL_HOURS", "1"))
        schedule.every(pro_interval_h).hours.do(
            schedule_async, "pro_automation", pro_automation_wrapper
        )
        logger.info("Registered pro_automation every %sh.", pro_interval_h)

    # Pro Insight retention (90-day default)
    pro_retention_time = os.getenv("PRO_STRUCTURAL_RETENTION_UTC_TIME", "04:15")
    schedule.every().day.at(pro_retention_time).do(
        schedule_async,
        "pro_structural_retention",
        run_pro_structural_retention_wrapper,
    )
    logger.info("Registered pro_structural_retention daily at %s.", pro_retention_time)

    # CFTC Commitments of Traders — weekly Tuesday afternoon (CFTC publishes Fri,
    # but Tuesday gives us the prior week's confirmed report).
    cftc_sync_day = os.getenv("CFTC_SYNC_DAY", "tuesday").lower()
    cftc_sync_time = os.getenv("CFTC_SYNC_UTC_TIME", "21:30")  # 17:30 ET = 21:30 UTC
    cftc_dispatcher = {
        "monday": schedule.every().monday,
        "tuesday": schedule.every().tuesday,
        "wednesday": schedule.every().wednesday,
        "thursday": schedule.every().thursday,
        "friday": schedule.every().friday,
        "saturday": schedule.every().saturday,
        "sunday": schedule.every().sunday,
    }.get(cftc_sync_day, schedule.every().tuesday)
    cftc_dispatcher.at(cftc_sync_time).do(
        schedule_async,
        "cftc_sync",
        run_cftc_sync_wrapper,
    )
    logger.info("Registered cftc_sync every %s at %s UTC.", cftc_sync_day, cftc_sync_time)

    # OpenSanctions bulk dump — daily ingestion + PageRank recompute.
    sanctions_sync_time = os.getenv("SANCTIONS_SYNC_UTC_TIME", "05:30")
    schedule.every().day.at(sanctions_sync_time).do(
        schedule_async,
        "sanctions_sync",
        run_sanctions_sync_wrapper,
    )
    logger.info("Registered sanctions_sync daily at %s UTC.", sanctions_sync_time)

async def run_startup_checks():
    """Execute immediate tests to verify environment health on startup."""
    skip_pipeline = os.getenv("SCHEDULER_SKIP_STARTUP_PIPELINE", "").lower() in (
        "true",
        "1",
        "yes",
    )
    if skip_pipeline:
        logger.info(
            "SCHEDULER_SKIP_STARTUP_PIPELINE=true — skipping startup pipeline_full_processing"
        )
    else:
        logger.info("Triggering IMMEDIATE startup pipeline (ingest → normalize → signal)...")
        await pipeline_full_processing()

    logger.info("Running startup operational audits...")
    async with AsyncSessionLocal() as session:
        await run_db_size_check(session)
        await enforce_metadata_limits(session)
        await audit_metadata_sizes(session)

    pro_on_startup = os.getenv("PRO_AUTOMATION_ON_STARTUP", "true").lower() in ("true", "1", "yes")
    logger.info("PRO_AUTOMATION_ON_STARTUP=%s", pro_on_startup)
    if pro_on_startup:
        logger.info("Triggering immediate rule-based Pro Structural Brief compile (6 domains)...")
        try:
            stream = await pro_automation_wrapper()
            logger.info(
                "Startup pro compile complete: inserted=%s status=%s elapsed_sec=%.2f",
                stream.get("inserted_count"),
                stream.get("status"),
                stream.get("elapsed_sec") or 0,
            )
        except Exception as e:
            logger.error("Startup pro_automation failed: %s", e)

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

    # Startup catch-up: the monthly_trend snapshot otherwise stays stale until the
    # next :30 after a (re)start — the audit saw a ~2h post-deploy lag. Kick one
    # rebuild now, non-blocking, so the dashboard is fresh immediately. The hourly
    # `every().hour.at(":30")` schedule continues to run normally; safe_run's
    # name-guard means an overlapping :30 fire is simply skipped, not duplicated.
    asyncio.create_task(safe_run("monthly_trend", monthly_trend_wrapper))

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
