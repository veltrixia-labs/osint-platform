import os
import time
import logging
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import delete, func, Text, cast, update
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db_size_mb
from db.models import AlertLog, AlertDelivery, Report, RawItem, Item, ItemTopic, AnalyticsEvent, SecurityLog, SystemMetric
from config.settings import settings

logger = logging.getLogger(__name__)

async def update_system_metric(db: AsyncSession, key: str, value: str):
    """Update or create a system metric record."""
    try:
        stmt = select(SystemMetric).where(SystemMetric.metric_key == key)
        result = await db.execute(stmt)
        metric = result.scalar_one_or_none()
        if metric:
            metric.metric_value = value
        else:
            db.add(SystemMetric(metric_key=key, metric_value=value))
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to update system metric {key}: {e}")

async def send_webhook_notification(message: str, level: str = "warning"):
    """Send alert to external monitoring webhook."""
    webhook_url = settings.monitoring_webhook_url
    if not webhook_url:
        logger.info(f"[NO WEBHOOK] External Alert ({level}): {message}")
        return

    payload = {
        "text": f"[{level.upper()}] OSINT Platform: {message}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=5.0)
            if resp.status_code >= 400:
                logger.error(f"Webhook failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")

async def run_alert_cleanup(db: AsyncSession, dry_run: bool | None = None):
    """
    Delete alerts older than 24 hours.
    """
    if dry_run is None: dry_run = settings.retention_dry_run
    mode = "[DRY RUN] " if dry_run else ""
    
    logger.info(f"{mode}Alert cleanup started")
    start_time = time.time()
    threshold = datetime.now(timezone.utc) - timedelta(hours=settings.alert_retention_hours)
    
    try:
        stmt = select(AlertLog.id).where(AlertLog.triggered_at < threshold)
        result = await db.execute(stmt)
        alert_ids = result.scalars().all()
        
        if not alert_ids:
            logger.info(f"{mode}Purged 0 alerts (No candidates found)")
            if not dry_run:
                await update_system_metric(db, "last_alert_cleanup_at", datetime.now(timezone.utc).isoformat())
            return

        # Delete linked deliveries
        del_stmt = delete(AlertDelivery).where(AlertDelivery.alert_log_id.in_(alert_ids))
        if not dry_run:
            del_res = await db.execute(del_stmt)
            logger.info(f"Purged {del_res.rowcount} alert deliveries")
        
        logs_stmt = delete(AlertLog).where(AlertLog.id.in_(alert_ids))
        if dry_run:
            logger.info(f"{mode}Would purge {len(alert_ids)} alerts.")
        else:
            logs_res = await db.execute(logs_stmt)
            logger.info(f"Purged {logs_res.rowcount} alerts")
            await db.commit()
            await update_system_metric(db, "last_alert_cleanup_at", datetime.now(timezone.utc).isoformat())
            
        elapsed = time.time() - start_time
        logger.info(f"{mode}Alert cleanup completed (Time: {elapsed:.2f}s)")
    except Exception as e:
        await db.rollback()
        logger.error(f"Alert cleanup failed: {e}")
        await send_webhook_notification(f"Alert cleanup failed: {e}", level="error")
        raise

async def run_retention_cleanup(db: AsyncSession, dry_run: bool | None = None):
    """
    High-level data retention cleanup.
    """
    if dry_run is None: dry_run = settings.retention_dry_run
    mode = "[DRY RUN] " if dry_run else ""
    
    logger.info(f"{mode}Retention cleanup started")
    start_time = time.time()
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=settings.report_retention_days)
    
    try:
        # --- 1. Report Cleanup ---
        PERSISTENT_TYPES = ["weekly_global", "monthly_global"]
        report_stmt = delete(Report).where(
            Report.created_at < threshold,
            Report.report_type.notin_(PERSISTENT_TYPES)
        )
        if not dry_run:
            report_res = await db.execute(report_stmt)
            logger.info(f"Purged {report_res.rowcount} reports")

        # --- 2. Logs/Analytics ---
        analytics_stmt = delete(AnalyticsEvent).where(AnalyticsEvent.created_at < threshold)
        security_stmt = delete(SecurityLog).where(SecurityLog.created_at < threshold)
        if not dry_run:
            a_res = await db.execute(analytics_stmt)
            s_res = await db.execute(security_stmt)
            logger.info(f"Purged {a_res.rowcount} analytics events")
            logger.info(f"Purged {s_res.rowcount} security logs")

        # --- 3. Raw Data (Dependency Aware) ---
        if await _is_monthly_summary_ready(db):
            logger.info(f"{mode}Monthly summary check passed. Proceeding with raw data purge...")
            it_stmt = delete(ItemTopic).where(ItemTopic.created_at < threshold)
            item_stmt = delete(Item).where(Item.created_at < threshold)
            raw_stmt = delete(RawItem).where(RawItem.created_at < threshold)
            
            if dry_run:
                logger.info(f"{mode}Would purge raw data older than {threshold}")
            else:
                it_res = await db.execute(it_stmt)
                item_res = await db.execute(item_stmt)
                raw_res = await db.execute(raw_stmt)
                logger.info(f"Purged {raw_res.rowcount} raw items")
                logger.info(f"Purged {item_res.rowcount} items")
        else:
            logger.warning("Skipped raw cleanup because monthly summary not found")
            await send_webhook_notification("Raw data cleanup skipped: Monthly summary missing", level="warning")

        if not dry_run:
            await db.commit()
            await update_system_metric(db, "last_retention_cleanup_at", datetime.now(timezone.utc).isoformat())
            
        elapsed = time.time() - start_time
        logger.info(f"{mode}Retention cleanup completed (Time: {elapsed:.2f}s)")
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Retention cleanup failed: {e}")
        await send_webhook_notification(f"Retention cleanup failed: {e}", level="error")
        raise

async def run_db_size_check(db: AsyncSession):
    """
    Monitor database file size and log occupancy status.
    """
    logger.info("Starting DB pressure monitoring check...")
    
    size_mb = await get_db_size_mb(db)
    await update_system_metric(db, "db_size_mb", f"{size_mb:.2f}")
    
    if size_mb >= settings.db_size_critical_mb:
        msg = f"DB PRESSURE CRITICAL: {size_mb:.2f}MB (Threshold: {settings.db_size_critical_mb}MB)"
        logger.critical(msg)
        await send_webhook_notification(msg, level="critical")
        # EMERGENCY CLEANUP (Skip dry run check)
        logger.warning("Triggering EMERGENCY cleanup...")
        await run_alert_cleanup(db, dry_run=False)
        await run_retention_cleanup(db, dry_run=False)
    elif size_mb >= settings.db_size_warning_mb:
        msg = f"DB PRESSURE WARNING: {size_mb:.2f}MB (Threshold: {settings.db_size_warning_mb}MB)"
        logger.warning(msg)
        await send_webhook_notification(msg, level="warning")

async def run_retention_audit(db: AsyncSession):
    """
    Self-check layer to verify that no stale data remains in production.
    """
    logger.info("Starting Retention Integrity Audit...")
    try:
        now = datetime.now(timezone.utc)
        
        # 1. Check for stale alerts (> 24h)
        alert_thresh = now - timedelta(hours=settings.alert_retention_hours + 1) # 1h buffer
        stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at < alert_thresh)
        stale_alerts = (await db.execute(stmt)).scalar() or 0
        if stale_alerts > 0:
            await send_webhook_notification(f"Audit Failure: Found {stale_alerts} stale alerts despite cleanup.", level="warning")
            
        # 2. Verify summary reports exist
        stmt_sum = select(func.count(Report.id)).where(Report.report_type == "monthly_global")
        summaries = (await db.execute(stmt_sum)).scalar() or 0
        if summaries == 0:
            logger.error("Audit Failure: No monthly summaries found!")
            await send_webhook_notification("Audit Failure: No monthly summaries found in database!", level="error")
            
        logger.info("Retention audit completed.")
    except Exception as e:
        logger.error(f"Retention audit failed: {e}")

async def enforce_metadata_limits(db: AsyncSession):
    """
    Proactively truncate exceptionally large payload fields.
    """
    try:
        stmt = select(AlertLog).where(func.length(cast(AlertLog.metadata_json, Text)) > settings.metadata_max_size_chars)
        res = await db.execute(stmt)
        oversized = res.scalars().all()
        if oversized:
            logger.warning(f"Detected {len(oversized)} oversized AlertLog entries. Truncating...")
            for a in oversized:
                a.metadata_json = {"error": "payload_truncated", "reason": "exceeded_storage_limit"}
            await db.commit()
            await send_webhook_notification(f"Metadata limit enforced: {len(oversized)} records truncated.", level="warning")
    except Exception as e:
        logger.error(f"Metadata limit enforcement failed: {e}")

async def audit_metadata_sizes(db: AsyncSession):
    """Observability helper."""
    try:
        stmt = select(AlertLog).limit(10)
        res = await db.execute(stmt)
        alerts = res.scalars().all()
        if alerts:
            alerts.sort(key=lambda a: len(str(a.metadata_json or "")), reverse=True)
            for a in alerts[:3]:
                size = len(str(a.metadata_json or ""))
                if size > settings.metadata_max_size_chars * 0.8:
                    await send_webhook_notification(f"Record {a.id} approaching metadata limit: {size} chars", level="warning")
    except Exception as e:
        logger.error(f"Metadata audit failed: {e}")

async def _is_monthly_summary_ready(db: AsyncSession) -> bool:
    threshold = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = select(Report).where(Report.report_type == "monthly_global", Report.created_at >= threshold)
    result = await db.execute(stmt)
    return result.scalars().first() is not None
