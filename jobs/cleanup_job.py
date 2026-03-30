import os
import sys
import shutil
import logging
import argparse
import json
import time
import httpx
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.future import select
from sqlalchemy import delete, func, Text, cast, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import AsyncSessionLocal, get_db_size_mb
from db.models import (
    AlertLog, AlertDelivery, Report, RawItem, Item, ItemTopic, 
    AnalyticsEvent, SecurityLog, SystemMetric, EventCluster, 
    AnalysisCache, TrendSignal
)
from config.settings import settings

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_RETENTION_DAYS = 14
SAFETY_WINDOW_DAYS = 7
MAX_DELETE_PER_RUN = 50

# --- Shared Helpers ---

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

# --- Visual Asset Cleanup (New Logic) ---

class VisualAudit:
    def __init__(self, dry_run=True, archive_only=False, retention_days=DEFAULT_RETENTION_DAYS):
        self.dry_run = dry_run
        self.archive_only = archive_only
        self.retention_days = retention_days
        
        self.base_dir = os.getcwd()
        self.visuals_dir = os.path.join(self.base_dir, "outputs", "visuals")
        self.archive_dir = os.path.join(self.base_dir, "outputs", "archive")
        self.outputs_dir = os.path.join(self.base_dir, "outputs")
        
        os.makedirs(self.archive_dir, exist_ok=True)
        
        self.referenced_files = set()
        self.all_files = []
        self.stats = {
            "total_scanned": 0,
            "referenced": 0,
            "unreferenced_recent": 0,
            "unreferenced_old": 0,
            "legacy_pattern": 0,
            "uncertain": 0,
            "archived": 0,
            "deleted": 0,
            "skipped": 0,
            "reclaimed_mb": 0.0
        }

    async def build_reference_map(self):
        """Query DB and local files for any mention of visual filenames."""
        logger.info("Building reference map...")
        
        async with AsyncSessionLocal() as db:
            # 1. Query Reports
            stmt_reports = select(Report.content_markdown, Report.teaser_md)
            reports = (await db.execute(stmt_reports)).all()
            for r_content, r_teaser in reports:
                self._extract_from_text(r_content)
                self._extract_from_text(r_teaser)
            
            # 2. Query AlertLog metadata
            stmt_alerts = select(AlertLog.metadata_json)
            alerts = (await db.execute(stmt_alerts)).scalars().all()
            for meta in alerts:
                if meta:
                    self._extract_from_text(json.dumps(meta))
        
        # 3. Scan outputs directory for markdown files
        for root, dirs, files in os.walk(self.outputs_dir):
            if "visuals" in root or "archive" in root: continue
            for file in files:
                if file.endswith(".md"):
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                            self._extract_from_text(f.read())
                    except Exception as e:
                        logger.warning(f"Could not read markdown file {file}: {e}")

        logger.info(f"Found {len(self.referenced_files)} unique referenced visuals.")

    def _extract_from_text(self, text):
        if not text: return
        matches = re.findall(r'visual_[a-zA-Z0-9_]+\.png', text)
        for m in matches:
            self.referenced_files.add(m)

    def classify_and_process(self):
        """Main classification and execution loop."""
        if not os.path.exists(self.visuals_dir):
            logger.warning(f"Visuals directory not found: {self.visuals_dir}")
            return
            
        self.all_files = [f for f in os.listdir(self.visuals_dir) if f.endswith(".png")]
        self.stats["total_scanned"] = len(self.all_files)
        
        now = datetime.now()
        candidates_for_deletion = []

        for filename in self.all_files:
            file_path = os.path.join(self.visuals_dir, filename)
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            age_days = (now - mtime).days
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            # Classification
            is_referenced = filename in self.referenced_files
            is_recent = age_days <= SAFETY_WINDOW_DAYS
            is_aged = age_days > self.retention_days
            
            is_legacy = not (filename.startswith("visual_") and filename.endswith(".png"))
            
            if is_referenced:
                self.stats["referenced"] += 1
                status = "REFERENCED"
            elif is_recent:
                self.stats["unreferenced_recent"] += 1
                status = "KEEP (RECENT)"
            elif is_aged:
                if is_legacy:
                    self.stats["legacy_pattern"] += 1
                    status = "ARCHIVE (LEGACY)"
                    self._archive_file(filename, size_mb)
                elif self._is_uncertain(filename):
                    self.stats["uncertain"] += 1
                    status = "ARCHIVE (UNCERTAIN)"
                    self._archive_file(filename, size_mb)
                else:
                    self.stats["unreferenced_old"] += 1
                    status = "DELETE CANDIDATE"
                    candidates_for_deletion.append((filename, size_mb))
            else:
                status = "KEEP (WITHIN RETENTION)"
                self.stats["skipped"] += 1

            logger.debug(f"{filename} | Age: {age_days}d | Status: {status}")

        if len(candidates_for_deletion) > MAX_DELETE_PER_RUN:
            logger.warning(f"!!! SAFETY LIMIT REACHED !!! Candidates ({len(candidates_for_deletion)}) exceed MAX_DELETE_PER_RUN ({MAX_DELETE_PER_RUN}).")
            return

        for filename, size_mb in candidates_for_deletion:
            if self.archive_only:
                self._archive_file(filename, size_mb)
            elif not self.dry_run:
                if self._final_defensive_check(filename):
                    logger.info(f"Safety Guard 2 triggered for {filename}. Skipping deletion.")
                    self.stats["skipped"] += 1
                    continue
                    
                self._delete_file(filename, size_mb)
            else:
                logger.info(f"[DRY-RUN] Would delete: {filename} ({size_mb:.2f} MB)")
                self.stats["reclaimed_mb"] += size_mb

    def _is_uncertain(self, filename):
        if not re.match(r'visual_[a-z_]+_\d{8}_[a-z0-9_]+\.png', filename):
            return True
        return False

    def _final_defensive_check(self, filename):
        return filename in self.referenced_files

    def _archive_file(self, filename, size_mb):
        src = os.path.join(self.visuals_dir, filename)
        dst = os.path.join(self.archive_dir, filename)
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would archive: {filename}")
        else:
            try:
                shutil.move(src, dst)
                logger.info(f"Archived: {filename}")
                self.stats["archived"] += 1
            except Exception as e:
                logger.error(f"Failed to archive {filename}: {e}")

    def _delete_file(self, filename, size_mb):
        file_path = os.path.join(self.visuals_dir, filename)
        try:
            os.remove(file_path)
            logger.info(f"Deleted: {filename}")
            self.stats["deleted"] += 1
            self.stats["reclaimed_mb"] += size_mb
        except Exception as e:
            logger.error(f"Failed to delete {filename}: {e}")

    def report(self):
        logger.info("--- Cleanup Audit Report ---")
        for k, v in self.stats.items():
            logger.info(f"{k.replace('_', ' ').capitalize()}: {v}")
        logger.info("----------------------------")

async def run_visual_cleanup(dry_run=False, archive_only=False, retention=DEFAULT_RETENTION_DAYS):
    """Entry point for the scheduler."""
    logger.info(f"Starting Visual Asset Cleanup (dry_run={dry_run}, archive_only={archive_only}, retention={retention})")
    audit = VisualAudit(dry_run=dry_run, archive_only=archive_only, retention_days=retention)
    await audit.build_reference_map()
    audit.classify_and_process()
    audit.report()

# --- Scheduler Critical Functions (Restored) ---

async def run_alert_cleanup(db: AsyncSession, dry_run: bool | None = None):
    """Delete alerts older than retention period."""
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

async def run_trend_cleanup(db: AsyncSession):
    """Cleanup for trend_signals (TTL + Row Cap)."""
    logger.info("Trend signals cleanup started")
    start_time = time.time()
    
    try:
        # 1. TTL Cleanup (72h)
        # Using raw SQL for compatibility with interval logic across DB providers
        ttl_stmt = text("DELETE FROM trend_signals WHERE created_at < NOW() - INTERVAL '72 hours'")
        try:
            ttl_res = await db.execute(ttl_stmt)
            logger.info(f"TTL Purged trend signals: {ttl_res.rowcount}")
        except Exception:
            # SQLite fallback for local development
            thresh = datetime.now(timezone.utc) - timedelta(hours=72)
            ttl_stmt = delete(TrendSignal).where(TrendSignal.created_at < thresh)
            ttl_res = await db.execute(ttl_stmt)
            logger.info(f"TTL Purged (SQLite Fallback): {ttl_res.rowcount}")

        # 2. Row Cap (20,000)
        cap_stmt = text("""
            DELETE FROM trend_signals
            WHERE created_at < (
              SELECT created_at FROM trend_signals
              ORDER BY created_at DESC OFFSET 20000 LIMIT 1
            )
            AND (SELECT COUNT(*) FROM trend_signals) > 20000
        """)
        try:
            cap_res = await db.execute(cap_stmt)
            if cap_res.rowcount > 0:
                logger.info(f"Row Cap Purged trend signals: {cap_res.rowcount}")
        except Exception:
            logger.warning("Complexity in Row Cap query. Skipping for this cycle.")

        await db.commit()
        await update_system_metric(db, "last_trend_cleanup_at", datetime.now(timezone.utc).isoformat())
        
        elapsed = time.time() - start_time
        logger.info(f"Trend signals cleanup completed (Time: {elapsed:.2f}s)")
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Trend signals cleanup failed: {e}")
        await send_webhook_notification(f"Trend signals cleanup failed: {e}", level="error")

async def run_retention_cleanup(db: AsyncSession, dry_run: bool | None = None):
    """High-level data retention cleanup (Reports, Analytics, Raw Data)."""
    if dry_run is None: dry_run = settings.retention_dry_run
    mode = "[DRY RUN] " if dry_run else ""
    
    logger.info(f"{mode}Retention cleanup started")
    start_time = time.time()
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=settings.report_retention_days)
    
    try:
        # 1. Report Cleanup
        PERSISTENT_TYPES = ["weekly_global", "monthly_global"]
        report_stmt = delete(Report).where(
            Report.created_at < threshold,
            Report.report_type.notin_(PERSISTENT_TYPES)
        )
        if not dry_run:
            report_res = await db.execute(report_stmt)
            logger.info(f"Purged {report_res.rowcount} reports")

        # 2. Logs/Analytics
        analytics_stmt = delete(AnalyticsEvent).where(AnalyticsEvent.created_at < threshold)
        security_stmt = delete(SecurityLog).where(SecurityLog.created_at < threshold)
        if not dry_run:
            await db.execute(analytics_stmt)
            await db.execute(security_stmt)

        # 3. Raw Data (Dependency Aware)
        if await _is_monthly_summary_ready(db):
            cluster_threshold = now - timedelta(days=31)
            cluster_sub = select(EventCluster.id).where(EventCluster.created_at < cluster_threshold)
            
            null_stmt = update(Item).where(Item.cluster_id.in_(cluster_sub)).values(cluster_id=None)
            cache_stmt = delete(AnalysisCache).where(AnalysisCache.created_at < threshold)
            it_stmt = delete(ItemTopic).where(ItemTopic.created_at < threshold)
            item_stmt = delete(Item).where(Item.created_at < threshold)
            raw_stmt = delete(RawItem).where(RawItem.created_at < threshold)
            
            if not dry_run:
                await db.execute(null_stmt)
                await db.execute(cache_stmt)
                await db.execute(it_stmt)
                await db.execute(item_stmt)
                await db.execute(raw_stmt)
                
                cluster_del_stmt = delete(EventCluster).where(EventCluster.id.in_(cluster_sub))
                await db.execute(cluster_del_stmt)

        if not dry_run:
            await db.commit()
            await update_system_metric(db, "last_retention_cleanup_at", datetime.now(timezone.utc).isoformat())
            
        elapsed = time.time() - start_time
        logger.info(f"{mode}Retention cleanup completed (Time: {elapsed:.2f}s)")
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Retention cleanup failed: {e}")
        raise

async def run_db_size_check(db: AsyncSession):
    """Monitor database file size and log occupancy status."""
    logger.info("Starting DB pressure monitoring check...")
    
    size_mb = await get_db_size_mb(db)
    await update_system_metric(db, "db_size_mb", f"{size_mb:.2f}")
    
    if size_mb >= settings.db_size_critical_mb:
        msg = f"DB PRESSURE CRITICAL: {size_mb:.2f}MB (Threshold: {settings.db_size_critical_mb}MB)"
        logger.critical(msg)
        await send_webhook_notification(msg, level="critical")
        logger.warning("Triggering EMERGENCY cleanup...")
        await run_alert_cleanup(db, dry_run=False)
        await run_retention_cleanup(db, dry_run=False)
    elif size_mb >= settings.db_size_warning_mb:
        msg = f"DB PRESSURE WARNING: {size_mb:.2f}MB (Threshold: {settings.db_size_warning_mb}MB)"
        logger.warning(msg)
        await send_webhook_notification(msg, level="warning")

async def run_retention_audit(db: AsyncSession):
    """Self-check layer to verify that no stale data remains."""
    logger.info("Starting Retention Integrity Audit...")
    try:
        now = datetime.now(timezone.utc)
        alert_thresh = now - timedelta(hours=settings.alert_retention_hours + 1)
        stmt = select(func.count(AlertLog.id)).where(AlertLog.triggered_at < alert_thresh)
        stale_alerts = (await db.execute(stmt)).scalar() or 0
        if stale_alerts > 0:
            await send_webhook_notification(f"Audit Failure: Found {stale_alerts} stale alerts.", level="warning")
            
        stmt_sum = select(func.count(Report.id)).where(Report.report_type == "monthly_global")
        summaries = (await db.execute(stmt_sum)).scalar() or 0
        if summaries == 0:
            logger.error("Audit Failure: No monthly summaries found!")
            
        logger.info("Retention audit completed.")
    except Exception as e:
        logger.error(f"Retention audit failed: {e}")

async def enforce_metadata_limits(db: AsyncSession):
    """Truncate exceptionally large payload fields."""
    try:
        stmt = select(AlertLog).where(func.length(cast(AlertLog.metadata_json, Text)) > settings.metadata_max_size_chars)
        res = await db.execute(stmt)
        oversized = res.scalars().all()
        if oversized:
            logger.warning(f"Detected {len(oversized)} oversized AlertLog entries. Truncating...")
            for a in oversized:
                a.metadata_json = {"error": "payload_truncated", "reason": "exceeded_storage_limit"}
            await db.commit()
    except Exception as e:
        logger.error(f"Metadata limit enforcement failed: {e}")

async def audit_metadata_sizes(db: AsyncSession):
    """Observability helper for payload sizes."""
    try:
        stmt = select(AlertLog).limit(10)
        res = await db.execute(stmt)
        alerts = res.scalars().all()
        if alerts:
            alerts.sort(key=lambda a: len(str(a.metadata_json or "")), reverse=True)
            for a in alerts[:3]:
                size = len(str(a.metadata_json or ""))
                if size > settings.metadata_max_size_chars * 0.8:
                    logger.warning(f"Record {a.id} approaching metadata limit: {size} chars")
    except Exception as e:
        logger.error(f"Metadata audit failed: {e}")

async def _is_monthly_summary_ready(db: AsyncSession) -> bool:
    threshold = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = select(Report).where(Report.report_type == "monthly_global", Report.created_at >= threshold)
    result = await db.execute(stmt)
    return result.scalars().first() is not None

# --- CLI Implementation ---

async def main():
    parser = argparse.ArgumentParser(description="Cleanup and Monitoring Jobs.")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no changes.")
    parser.add_argument("--archive-only", action="store_true", help="Archive instead of delete (Visuals only).")
    parser.add_argument("--retention", type=int, default=DEFAULT_RETENTION_DAYS, help="Retention days (Visuals).")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Defaults to running Visual Cleanup when called via CLI
    audit = VisualAudit(dry_run=args.dry_run, archive_only=args.archive_only, retention_days=args.retention)
    await audit.build_reference_map()
    audit.classify_and_process()
    audit.report()

if __name__ == "__main__":
    asyncio.run(main())

