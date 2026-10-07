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
    AnalysisCache, TrendSignal, SignalRanking, IngestRejection
)
from config.settings import settings
from db.enums import RETIRED_REPORT_TYPES

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_RETENTION_DAYS = 14
# Rows per committed batch in run_retention_cleanup's raw-data phase (see the comment there).
RETENTION_BATCH_SIZE = 5000
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
            # 1. Query Reports — STREAMED in 500-row partitions. Only the small
            # set of referenced filenames accumulates; the full content_markdown /
            # teaser text is never materialized into one Python list.
            stmt_reports = select(Report.content_markdown, Report.teaser_md).execution_options(yield_per=500)
            async for r_content, r_teaser in await db.stream(stmt_reports):
                self._extract_from_text(r_content)
                self._extract_from_text(r_teaser)

            # 2. Query AlertLog metadata — STREAMED. Loading every metadata_json
            # blob into one list was the largest unbounded scan (OOM driver).
            stmt_alerts = select(AlertLog.metadata_json).execution_options(yield_per=500)
            async for meta in await db.stream_scalars(stmt_alerts):
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

async def run_retention_cleanup(db: AsyncSession, dry_run: bool | None = None) -> dict:
    """High-level data retention cleanup (Reports, Analytics, Raw Data).

    Returns {target: rows}. In dry-run mode the rows are COUNTED with the same WHERE clauses the
    real run deletes with, including the rows the FK cascades would remove, and nothing is
    written. (Until 2026-10-06 a dry run only logged "started/completed" and counted nothing.)
    """
    if dry_run is None: dry_run = settings.retention_dry_run
    mode = "[DRY RUN] " if dry_run else ""
    
    logger.info(f"{mode}Retention cleanup started")
    start_time = time.time()
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=settings.report_retention_days)
    # ★ RAW_RETENTION_DAYS was defined (config/settings.py) and read by nothing until 2026-10-06;
    #   raw data used report_retention_days. It now governs the raw tables. Default 30, so the
    #   cutoff is unchanged. Clusters keep their original one-day lag (31 at the default).
    raw_threshold = now - timedelta(days=settings.raw_retention_days)
    cluster_threshold = now - timedelta(days=settings.raw_retention_days + 1)
    counts: dict = {}

    async def _count(stmt_sel) -> int:
        return int((await db.execute(stmt_sel)).scalar() or 0)

    try:
        # 1. Report Cleanup (excludes pro_structural — see run_pro_structural_retention_cleanup)
        # ★ PERSISTENT_TYPES history:
        #   - It read ["weekly_global", "monthly_global", "pro_structural"] until 2026-10-06: stale
        #     names (4a2367d renamed the writers; 38d1356 restored the old names here), so weekly
        #     and monthly reports were deleted at 30 days.
        #   - It was fixed to ["weekly", "monthly", "pro_structural"] that evening (39d4929).
        #   - Hours later weekly/monthly were retired outright (db/enums.py RETIRED_REPORT_TYPES)
        #     and are deleted below regardless of age, so only pro_structural remains. It also has
        #     its own 90-day retention job.
        PERSISTENT_TYPES = ["pro_structural"]
        report_stmt = delete(Report).where(
            Report.created_at < threshold,
            Report.report_type.notin_(PERSISTENT_TYPES),
            ~Report.title.ilike("Structural Impact Brief%"),
        )
        # 1b. Retired report types (2026-10-06): deleted REGARDLESS OF AGE, not left to the 30-day
        #     rule. Waiting would keep the last row (weekly, 2026-10-05) until 2026-11-04, and any
        #     row written by a scheduler that has not yet been redeployed would sit another 30 days.
        #     Measured before this change: 0 rows in any table reference these reports, so the
        #     CASCADE (article_outputs, pdf_jobs, external_posts) and SET NULL (alert_logs,
        #     report_trigger_logs, analytics_events) paths remove or clear nothing.
        retired_stmt = delete(Report).where(Report.report_type.in_(RETIRED_REPORT_TYPES))
        if dry_run:
            counts["reports"] = await _count(select(func.count(Report.id)).where(
                Report.created_at < threshold,
                Report.report_type.notin_(PERSISTENT_TYPES),
                Report.report_type.notin_(RETIRED_REPORT_TYPES),
                ~Report.title.ilike("Structural Impact Brief%")))
            counts["reports_retired_types"] = await _count(select(func.count(Report.id)).where(
                Report.report_type.in_(RETIRED_REPORT_TYPES)))
        else:
            report_res = await db.execute(report_stmt)
            counts["reports"] = report_res.rowcount
            counts["reports_retired_types"] = (await db.execute(retired_stmt)).rowcount
            logger.info(f"Purged {report_res.rowcount} reports (age) + {counts['reports_retired_types']} retired-type reports")

        # 2. Logs/Analytics
        analytics_stmt = delete(AnalyticsEvent).where(AnalyticsEvent.created_at < threshold)
        security_stmt = delete(SecurityLog).where(SecurityLog.created_at < threshold)
        if not dry_run:
            await db.execute(analytics_stmt)
            await db.execute(security_stmt)

        # 2b. ingest_rejections (2026-10-07): the stale-on-arrival filter's record, one row per
        #     entry. Kept INGEST_REJECTION_RETENTION_DAYS (90) after the entry was LAST seen, so a
        #     feed that keeps re-serving an entry keeps its row.
        rej_threshold = now - timedelta(days=settings.ingest_rejection_retention_days)
        if dry_run:
            counts["ingest_rejections"] = await _count(select(func.count()).select_from(IngestRejection).where(
                IngestRejection.last_rejected_at < rej_threshold))
        else:
            counts["ingest_rejections"] = (await db.execute(delete(IngestRejection).where(
                IngestRejection.last_rejected_at < rej_threshold))).rowcount

        # 3. Raw Data
        # ★ The gate that stood here was removed 2026-10-06: `if await _is_monthly_summary_ready(db):`,
        #   which required a report with report_type == "monthly_global" in the last 30 days. The
        #   generator has written "monthly" since 4a2367d (2026-03-26), and 38d1356 restored the old
        #   name here, so the gate never opened. items / raw_items / event_clusters /
        #   analysis_cache / item_topics were NEVER pruned (production 2026-10-06: items back to
        #   2026-03-23). It was removed rather than corrected, because it protects nothing the cutoff
        #   below does not: the monthly report reads signal_rankings (24h), event_clusters (1h/24h),
        #   trend_signals (24h) and items only by ranked id or a published_at >= 30-day fallback, and
        #   never reads raw_items, analysis_cache or item_topics. A corrected string would leave a
        #   dependency that silently stops ALL raw deletion whenever one monthly generation fails.
        cluster_sub = select(EventCluster.id).where(EventCluster.created_at < cluster_threshold)
        old_item_ids = select(Item.id).where(Item.created_at < raw_threshold)

        if dry_run:
            # Counted exactly as the batched run below deletes: the dependants of old items PLUS
            # dependants old in their own right.
            counts["analysis_cache"] = await _count(select(func.count()).select_from(AnalysisCache).where(
                (AnalysisCache.created_at < raw_threshold) | AnalysisCache.item_id.in_(old_item_ids)))
            counts["item_topics"] = await _count(select(func.count()).select_from(ItemTopic).where(
                (ItemTopic.created_at < raw_threshold) | ItemTopic.item_id.in_(old_item_ids)))
            counts["signal_rankings_cascade"] = await _count(select(func.count()).select_from(SignalRanking).where(
                SignalRanking.item_id.in_(old_item_ids)))
            counts["items"] = await _count(select(func.count()).select_from(Item).where(Item.created_at < raw_threshold))
            counts["raw_items"] = await _count(select(func.count()).select_from(RawItem).where(RawItem.created_at < raw_threshold))
            counts["items_cluster_nulled"] = await _count(select(func.count()).select_from(Item).where(
                Item.created_at >= raw_threshold, Item.cluster_id.in_(cluster_sub)))
            counts["event_clusters"] = await _count(select(func.count()).select_from(EventCluster).where(
                EventCluster.created_at < cluster_threshold))
            elapsed = time.time() - start_time
            logger.info(f"{mode}Retention cleanup completed (Time: {elapsed:.2f}s) would delete: {counts}")
            return counts

        # Reports / analytics / security logs are small. Commit them first, as one unit.
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Retention cleanup failed before raw-data phase: {e}")
        raise

    # ── Raw data: BATCHED (2026-10-06) ─────────────────────────────────────────────────────
    # The first run after the gate's removal deletes ~217k rows (~138MB of row data). In ONE
    # transaction that writes a WAL spike we cannot bound, because the WAL area is not readable with
    # the production role, against a disk at ~539MB of 1GB. Filling it would stop all writes. So
    # each batch of RETENTION_BATCH_SIZE rows commits on its own.
    #
    # ORDER: children before parents, explicitly, so no batch depends on ON DELETE CASCADE / SET
    # NULL to sort it out. The run spans minutes and new rows arrive while it runs.
    #   1. items, per batch of ids: first their dependants analysis_cache, item_topics,
    #      signal_rankings (all FK -> items), then the items themselves.
    #   2. analysis_cache / item_topics rows old in their own right (their item is newer).
    #   3. raw_items (no FKs either way).
    #   4. event_clusters, per batch of ids: first null items.cluster_id on surviving items that
    #      point at them (FK items.cluster_id -> event_clusters), then the clusters.
    #
    # TERMINATION. Each phase stops when a batch selects 0 rows. The cutoffs were computed once at
    #   the top, so rows that age past them during the run are not chased, and the matching set
    #   only shrinks. As a hard stop, each phase may run at most ceil(initial_count / batch) + 2
    #   batches. Hitting that cap with rows left marks the run INCOMPLETE, never successful.
    # FAILURE. Committed batches stay deleted. The failing batch is rolled back, the progress so far
    #   is logged and written to system_metrics.retention_last_result with status "failed", and
    #   the exception is re-raised. last_retention_cleanup_at is only stamped on full success.
    BATCH = RETENTION_BATCH_SIZE
    progress = {k: 0 for k in ("items", "analysis_cache", "item_topics", "signal_rankings",
                               "raw_items", "items_cluster_nulled", "event_clusters")}
    status, incomplete = "running", []

    async def _phase(name, select_ids, delete_batch):
        initial = await _count(select(func.count()).select_from(select_ids.subquery()))
        cap = -(-initial // BATCH) + 2
        for _ in range(cap):
            ids = [r[0] for r in (await db.execute(select_ids.limit(BATCH))).all()]
            if not ids:
                return
            await delete_batch(ids)
            await db.commit()
        if (await db.execute(select_ids.limit(1))).first() is not None:
            incomplete.append(name)

    async def _items_batch(ids):
        progress["analysis_cache"] += (await db.execute(delete(AnalysisCache).where(AnalysisCache.item_id.in_(ids)))).rowcount
        progress["item_topics"] += (await db.execute(delete(ItemTopic).where(ItemTopic.item_id.in_(ids)))).rowcount
        progress["signal_rankings"] += (await db.execute(delete(SignalRanking).where(SignalRanking.item_id.in_(ids)))).rowcount
        progress["items"] += (await db.execute(delete(Item).where(Item.id.in_(ids)))).rowcount

    async def _cache_batch(ids):
        progress["analysis_cache"] += (await db.execute(delete(AnalysisCache).where(AnalysisCache.id.in_(ids)))).rowcount

    async def _topics_batch(ids):
        progress["item_topics"] += (await db.execute(delete(ItemTopic).where(ItemTopic.id.in_(ids)))).rowcount

    async def _raw_batch(ids):
        progress["raw_items"] += (await db.execute(delete(RawItem).where(RawItem.id.in_(ids)))).rowcount

    async def _cluster_batch(ids):
        progress["items_cluster_nulled"] += (await db.execute(
            update(Item).where(Item.cluster_id.in_(ids)).values(cluster_id=None))).rowcount
        progress["event_clusters"] += (await db.execute(delete(EventCluster).where(EventCluster.id.in_(ids)))).rowcount

    try:
        await _phase("items", select(Item.id).where(Item.created_at < raw_threshold), _items_batch)
        await _phase("analysis_cache", select(AnalysisCache.id).where(AnalysisCache.created_at < raw_threshold), _cache_batch)
        await _phase("item_topics", select(ItemTopic.id).where(ItemTopic.created_at < raw_threshold), _topics_batch)
        await _phase("raw_items", select(RawItem.id).where(RawItem.created_at < raw_threshold), _raw_batch)
        await _phase("event_clusters", select(EventCluster.id).where(EventCluster.created_at < cluster_threshold), _cluster_batch)
        status = "incomplete" if incomplete else "success"
    except Exception as e:
        await db.rollback()
        status = "failed"
        counts.update(progress)
        logger.error(f"Retention cleanup FAILED in raw-data phase after committing {progress}: {e}")
        try:
            await update_system_metric(db, "retention_last_result", json.dumps(
                {"status": status, "at": datetime.now(timezone.utc).isoformat(), "deleted": progress, "error": str(e)[:300]}))
        except Exception:
            logger.error("Could not record retention_last_result after failure")
        raise

    counts.update(progress)
    await update_system_metric(db, "retention_last_result", json.dumps(
        {"status": status, "at": datetime.now(timezone.utc).isoformat(), "deleted": progress, "incomplete": incomplete}))
    elapsed = time.time() - start_time
    if status == "success":
        await update_system_metric(db, "last_retention_cleanup_at", datetime.now(timezone.utc).isoformat())
        logger.info(f"Retention cleanup completed (Time: {elapsed:.2f}s) deleted: {counts}")
    else:
        logger.error(f"Retention cleanup INCOMPLETE (Time: {elapsed:.2f}s): phases {incomplete} hit their batch cap; deleted so far: {counts}")
    return counts

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
            
        # ★ History of this check:
        #   - Until 2026-10-06 it counted report_type == "monthly_global", which nothing had written
        #     since March. It logged "No monthly summaries found!" every day: an alarm that fired
        #     correctly and that nobody read.
        #   - It was then pointed at "monthly", and hours later monthly was retired.
        #   - It now watches the product that superseded them, Pro Insight (pro_structural).
        # COLUMN: created_at. pro_report_generator overwrites created_at on update-in-place
        #   (existing.created_at = analysis_ts), so it records the latest regeneration. Measured
        #   2026-10-06: equal to structured_payload.analysis_generated_at on all 6 rows.
        # WINDOW: 48h. Measured: all 6 rows regenerated together at 09:29Z and again at 10:16Z,
        #   both around scheduler starts, and pro automation is scheduled every 30 min. Only the
        #   latest row per domain is kept, so the long-run interval could NOT be measured. When the
        #   compile anchor is unchanged a run SKIPS and created_at does not move, so a quiet news
        #   period longer than 48h would trip this. That is a known false-positive mode.
        recent_thresh = now - timedelta(hours=48)
        stmt_sum = select(func.count(Report.id)).where(
            Report.report_type == "pro_structural", Report.created_at >= recent_thresh)
        recent_briefs = (await db.execute(stmt_sum)).scalar() or 0
        if recent_briefs == 0:
            logger.error("Audit Failure: no Pro Insight (pro_structural) brief generated in the last 48h")
            await send_webhook_notification(
                "Audit Failure: no Pro Insight (pro_structural) brief generated in the last 48h", level="error")
            
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


async def run_pro_structural_retention_wrapper():
    """Scheduled purge of Pro Insight structural briefs older than PRO_STRUCTURAL_RETENTION_DAYS."""
    from jobs.pro_structural_retention import run_pro_structural_retention_cleanup

    async with AsyncSessionLocal() as session:
        await run_pro_structural_retention_cleanup(session, dry_run=settings.retention_dry_run)


# --- One-off: purge specific item rows (2026-10-07) ---
#
# Why this exists. The first batched retention run (2026-10-07 00:00Z) deleted six months of
# raw_items/items, and with them the dedup memory (raw_items.payload_hash, items.dedup_key). Feeds
# that still served old entries were re-ingested as NEW items, published 2025-12 .. 2026-09 but
# with today's created_at. GET /api/items orders by created_at and the feed list displays it, so
# they were shown to users as today's news (vault audit §12.66, §12.67).
#
# Why a targeted delete and not the retention job. Retention selects by created_at, and these
# rows were created today, so it cannot reach them for 30 days. Adding a "stale on arrival" phase
# to it would adopt a design (filter on published_at) that has not been decided.
#
# Why raw_items is never touched. The raw row's payload_hash is ingest's dedup memory; deleting
# it lets a feed that still serves the entry re-ingest it within one cycle.
#
# Why the normalize-lookback guard. run_normalize re-reads every raw row inside its lookback and
# dedups only against items.dedup_key. Deleting an item whose raw row is still inside that window
# re-creates the item on the next 5-minute cycle. The lookback is read from normalize.py's own
# source (it is an inline literal, not an importable constant), so this guard cannot drift from
# the code it protects; if that code changes shape, the guard refuses instead of guessing.

_NORMALIZE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "processor", "normalize.py")


def normalize_lookback_hours(path: str = _NORMALIZE_PATH) -> float:
    """The `hours=` of run_normalize's `lookback = … - timedelta(hours=N)`, read by AST (no import).

    Raises RuntimeError unless exactly one such assignment with a numeric literal is found."""
    import ast
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fns = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_normalize"]
    if len(fns) != 1:
        raise RuntimeError(f"normalize lookback: expected one run_normalize in {path}, found {len(fns)}")
    found = []
    for node in ast.walk(fns[0]):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "lookback" for t in node.targets):
            for call in ast.walk(node.value):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "timedelta":
                    for kw in call.keywords:
                        if kw.arg == "hours" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                            found.append(kw.value.value)
    if len(found) != 1:
        raise RuntimeError(f"normalize lookback: expected one `lookback = … timedelta(hours=<number>)` in run_normalize, found {found}")
    return float(found[0])


async def purge_items_by_id(db: AsyncSession, ids: List[str], *, expected_count: int,
                            dry_run: bool = True, stale_days: int = 30) -> Dict[str, Any]:
    """Delete exactly these `items` rows, or nothing. Dry run by default.

    Refuses (deletes nothing) unless ALL hold:
      (a) exactly `expected_count` distinct ids, all present in items;
      (b) every row is stale on arrival: published_at < created_at - stale_days;
      (c) nothing references them: 0 rows in analysis_cache / item_topics / signal_rankings, and
          cluster_id is NULL (so the delete cascades to nothing);
      (d) every row has >= 1 backing raw_items row, and EVERY backing raw row is older than
          normalize's lookback (read from processor/normalize.py), so normalize cannot re-create it;
      (e) raw_items is never touched.
    A dry run pins its transaction READ ONLY and verifies it. An executed run deletes in one
    transaction, asserts rowcount == expected_count or rolls back, and records the outcome in
    system_metrics.oneoff_item_purge_result (also on refusal)."""
    ids = sorted({str(i).strip() for i in ids if str(i).strip()})
    result: Dict[str, Any] = {"dry_run": dry_run, "requested": len(ids), "expected_count": expected_count,
                              "problems": [], "deleted": 0}
    if dry_run:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        ro = (await db.execute(text("SHOW transaction_read_only"))).scalar()
        if ro != "on":
            raise RuntimeError(f"dry run: transaction_read_only is {ro!r}, refusing")
        result["transaction_read_only"] = ro

    problems = result["problems"]
    lookback_h = normalize_lookback_hours()
    db_now = (await db.execute(text("SELECT now()"))).scalar()
    result.update({"normalize_lookback_hours": lookback_h, "db_now": db_now.isoformat()})

    # (a)
    if len(ids) != expected_count:
        problems.append(f"(a) {len(ids)} distinct ids, expected {expected_count}")
    stmt = select(Item.id, Item.published_at, Item.created_at, Item.cluster_id,
                  Item.source_id, Item.source_url).where(Item.id.in_(ids))
    if not dry_run:
        stmt = stmt.with_for_update()
    rows = (await db.execute(stmt)).all()
    found = {str(r.id) for r in rows}
    if len(rows) != len(ids):
        problems.append(f"(a) {len(rows)} of {len(ids)} ids present; missing {sorted(set(ids) - found)}")

    # (b) and the cluster half of (c)
    for r in rows:
        if r.published_at is None or r.published_at >= r.created_at - timedelta(days=stale_days):
            problems.append(f"(b) {r.id} not stale on arrival (published {r.published_at}, created {r.created_at})")
        if r.cluster_id is not None:
            problems.append(f"(c) {r.id} has cluster_id {r.cluster_id}")

    # (c) FK children (each CASCADEs from items)
    refs = {}
    for name, model in (("analysis_cache", AnalysisCache), ("item_topics", ItemTopic), ("signal_rankings", SignalRanking)):
        n = (await db.execute(select(func.count()).select_from(model).where(model.item_id.in_(ids)))).scalar() or 0
        refs[name] = n
        if n:
            problems.append(f"(c) {n} {name} rows reference these items")
    result["references"] = refs

    # (d) backing raw rows, matched by source_id + the item's URL inside payload_json
    cutoff = db_now - timedelta(hours=lookback_h)
    raw_rows, newest = 0, None
    for r in rows:
        if not r.source_url:
            problems.append(f"(d) {r.id} has no source_url; cannot locate its raw row")
            continue
        raws = (await db.execute(select(RawItem.created_at).where(
            RawItem.source_id == r.source_id,
            func.strpos(cast(RawItem.payload_json, Text), r.source_url) > 0))).scalars().all()
        if not raws:
            problems.append(f"(d) {r.id} has no backing raw_items row (ingest would not dedup it)")
        for ca in raws:
            raw_rows += 1
            newest = ca if newest is None or ca > newest else newest
            if ca >= cutoff:
                problems.append(f"(d) {r.id} raw row created {ca.isoformat()} is inside normalize's {lookback_h}h lookback (until {(ca + timedelta(hours=lookback_h)).isoformat()})")
    result.update({"backing_raw_rows": raw_rows, "newest_raw_created_at": newest.isoformat() if newest else None,
                   "raw_items_deleted": 0})

    if problems or dry_run:
        result["status"] = "refused" if problems else "dry_run_ok"
        await db.rollback()
        if problems and not dry_run:
            await update_system_metric(db, "oneoff_item_purge_result", json.dumps(result, default=str))
        return result

    res = await db.execute(delete(Item).where(Item.id.in_(ids)))
    if res.rowcount != expected_count:
        await db.rollback()
        result.update({"status": "rolled_back", "problems": [f"rowcount {res.rowcount} != {expected_count}"]})
        await update_system_metric(db, "oneoff_item_purge_result", json.dumps(result, default=str))
        return result
    await db.commit()
    result.update({"status": "deleted", "deleted": res.rowcount, "ids": ids,
                   "at": datetime.now(timezone.utc).isoformat()})
    await update_system_metric(db, "oneoff_item_purge_result", json.dumps(result, default=str))
    return result


async def _purge_items_cli(path: str, expected_count: int, execute: bool) -> int:
    with open(path, encoding="utf-8") as fh:
        ids = [ln.split("#", 1)[0].strip() for ln in fh]
    async with AsyncSessionLocal() as session:
        result = await purge_items_by_id(session, [i for i in ids if i], expected_count=expected_count,
                                         dry_run=not execute)
    print(json.dumps(result, indent=1, default=str))
    return 0 if result["status"] in ("dry_run_ok", "deleted") else 1

# --- CLI Implementation ---

async def main():
    parser = argparse.ArgumentParser(description="Cleanup and Monitoring Jobs.")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no changes.")
    parser.add_argument("--archive-only", action="store_true", help="Archive instead of delete (Visuals only).")
    parser.add_argument("--retention", type=int, default=DEFAULT_RETENTION_DAYS, help="Retention days (Visuals).")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--purge-items-file", help="One-off: file of item ids to purge (dry run unless --execute).")
    parser.add_argument("--expected-count", type=int, help="Required with --purge-items-file: exact number of ids.")
    parser.add_argument("--execute", action="store_true", help="With --purge-items-file: actually delete.")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.purge_items_file:
        if args.expected_count is None:
            parser.error("--expected-count is required with --purge-items-file")
        raise SystemExit(await _purge_items_cli(args.purge_items_file, args.expected_count, args.execute))
    if args.execute or args.expected_count is not None:
        parser.error("--execute / --expected-count are only valid with --purge-items-file")

    # Defaults to running Visual Cleanup when called via CLI
    audit = VisualAudit(dry_run=args.dry_run, archive_only=args.archive_only, retention_days=args.retention)
    await audit.build_reference_map()
    audit.classify_and_process()
    audit.report()

if __name__ == "__main__":
    asyncio.run(main())
