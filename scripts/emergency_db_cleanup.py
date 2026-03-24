import asyncio
import os
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete, func, text, select, update
from db.database import AsyncSessionLocal, get_db_size_mb
from db.models import RawItem, Item, ItemTopic, AlertLog, AlertDelivery, AnalyticsEvent, SecurityLog, AnalysisCache, Report, EventCluster

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("emergency_cleanup")

async def get_table_diagnostics(db):
    """Query PostgreSQL for table and index sizes."""
    query = text("""
        SELECT
            relname AS table_name,
            pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
            pg_size_pretty(pg_relation_size(relid)) AS table_size,
            pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) AS index_size,
            n_live_tup AS estimate_rows
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 15;
    """)
    res = await db.execute(query)
    return [dict(row) for row in res.mappings()]

async def get_index_diagnostics(db, table_name):
    """Query PostgreSQL for specific index sizes of a table."""
    query = text(f"""
        SELECT
            indexrelname AS index_name,
            pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
        FROM pg_stat_user_indexes
        WHERE relname = '{table_name}';
    """)
    res = await db.execute(query)
    return [dict(row) for row in res.mappings()]

async def run_phase_with_session(phase_name, func, results, *args, **kwargs):
    """Run a specific cleanup/diagnostic phase in a fresh, isolated session."""
    logger.info(f"--- PHASE START: {phase_name} ---")
    async with AsyncSessionLocal() as db:
        try:
            res = await func(db, *args, **kwargs)
            await db.commit()
            logger.info(f"--- PHASE SUCCESS: {phase_name} ---")
            return res
        except Exception as e:
            await db.rollback()
            logger.error(f"--- PHASE FAILED: {phase_name} ---")
            logger.error(f"Error in {phase_name}: {e}")
            # We don't raise here, we want other phases to continue
            return None

async def emergency_cleanup():
    logger.info("--- EMERGENCY DATABASE CLEANUP START (V6 - Session Isolated) ---")
    results = {
        "success": False, 
        "counts": {}, 
        "size_before": 0, 
        "size_after": 0, 
        "diagnostics_before": [],
        "diagnostics_after": [],
        "trend_signals_indices": [],
        "error": None
    }
    
    # --- 1. PRE-DIAGNOSTICS (Isolated Session) ---
    async with AsyncSessionLocal() as db_diag_pre:
        try:
            results["diagnostics_before"] = await get_table_diagnostics(db_diag_pre)
            results["trend_signals_indices"] = await get_index_diagnostics(db_diag_pre, "trend_signals")
            results["size_before"] = await get_db_size_mb(db_diag_pre)
            logger.info(f"DB Size BEFORE: {results['size_before']} MB")
        except Exception as de:
            logger.error(f"Pre-diagnostics failed: {de}")

    # --- 2. TRUNCATE PHASE (Isolated Session) ---
    async def do_truncate(db):
        logger.info("[P0] Executing TRUNCATE trend_signals CASCADE...")
        await db.execute(text("TRUNCATE TABLE trend_signals CASCADE;"))
        results["counts"]["trend_signals_truncated"] = True
    
    await run_phase_with_session("TRUNCATE trend_signals", do_truncate, results)

    # --- 3. DELETE PHASES (Individual Sessions) ---
    now = datetime.now(timezone.utc)

    async def del_raw(db):
        res = await db.execute(delete(RawItem).where(RawItem.created_at < (now - timedelta(hours=4))))
        results["counts"]["raw_items"] = res.rowcount
    await run_phase_with_session("DELETE RawItem (4h)", del_raw, results)

    async def del_clusters(db):
        # Nullify and Delete in same session but isolated from other tables
        cluster_threshold = now - timedelta(hours=12)
        old_clusters_sub = select(EventCluster.id).where(EventCluster.created_at < cluster_threshold)
        await db.execute(update(Item).where(Item.cluster_id.in_(old_clusters_sub)).values(cluster_id=None))
        res = await db.execute(delete(EventCluster).where(EventCluster.created_at < cluster_threshold))
        results["counts"]["event_clusters"] = res.rowcount
    await run_phase_with_session("DELETE EventCluster (12h)", del_clusters, results)

    async def del_alerts(db):
        res1 = await db.execute(delete(AlertDelivery).where(AlertDelivery.delivered_at < (now - timedelta(hours=24))))
        res2 = await db.execute(delete(AlertLog).where(AlertLog.triggered_at < (now - timedelta(hours=24))))
        results["counts"]["alert_deliveries"] = res1.rowcount
        results["counts"]["alert_logs"] = res2.rowcount
    await run_phase_with_session("DELETE Alerts (24h)", del_alerts, results)

    async def del_cache(db):
        res = await db.execute(delete(AnalysisCache).where(AnalysisCache.created_at < (now - timedelta(hours=24))))
        results["counts"]["analysis_cache"] = res.rowcount
    await run_phase_with_session("DELETE AnalysisCache (24h)", del_cache, results)

    # --- 4. VACUUM PHASE (Isolated Session) ---
    async def do_vacuum(db):
        for table in ["trend_signals", "raw_items", "event_clusters", "analysis_cache"]:
            try:
                await db.execute(text(f"VACUUM ANALYZE {table}"))
                logger.info(f"VACUUM ANALYZE {table} DONE")
            except Exception as ve:
                logger.warning(f"VACUUM ANALYZE {table} skipped: {ve}")
    await run_phase_with_session("VACUUM", do_vacuum, results)

    # --- 5. POST-DIAGNOSTICS (Isolated Session) ---
    async with AsyncSessionLocal() as db_diag_post:
        try:
            results["diagnostics_after"] = await get_table_diagnostics(db_diag_post)
            results["size_after"] = await get_db_size_mb(db_diag_post)
            results["success"] = True
            logger.info(f"DB Size AFTER: {results['size_after']} MB")
            logger.info(f"Space recovered: {round(results['size_before'] - results['size_after'], 2)} MB")
        except Exception as de:
            logger.error(f"Post-diagnostics failed: {de}")

    return results

if __name__ == "__main__":
    asyncio.run(emergency_cleanup())
