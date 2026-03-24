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

async def emergency_cleanup():
    logger.info("--- EMERGENCY DATABASE CLEANUP START ---")
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
    
    async with AsyncSessionLocal() as db:
        try:
            # --- 0. PRE-DIAGNOSTICS ---
            diag_before = await get_table_diagnostics(db)
            results["diagnostics_before"] = diag_before
            results["trend_signals_indices"] = await get_index_diagnostics(db, "trend_signals")
            
            size_before = await get_db_size_mb(db)
            results["size_before"] = size_before
            
            logger.info(f"DB Size BEFORE cleanup: {size_before} MB")
            for table in diag_before:
                if table['table_name'] == 'trend_signals':
                    logger.info(f"!!! CRITICAL BLOAT: trend_signals is {table['total_size']} with {table['estimate_rows']} rows")

            # --- 1. PRIORITY ZERO: TRUNCATE trend_signals ---
            # This is the primary target for 762MB bloat
            logger.info("[P0] Executing TRUNCATE trend_signals CASCADE...")
            try:
                await db.execute(text("TRUNCATE TABLE trend_signals CASCADE;"))
                await db.commit()
                results["counts"]["trend_signals_truncated"] = True
                logger.info("[P0] TRUNCATE trend_signals SUCCESS")
            except Exception as te:
                await db.rollback()
                logger.error(f"[P0] TRUNCATE trend_signals FAILED: {te}")
                # Continue other cleanups if possible

            # --- 2. PRIORITY 1: Aggressive Deletions ---
            now = datetime.now(timezone.utc)
            
            # Use individual commits to avoid bulk transaction failure
            async def run_step(name, stmt):
                try:
                    res = await db.execute(stmt)
                    await db.commit()
                    results["counts"][name] = res.rowcount
                    logger.info(f"Step {name}: Deleted {res.rowcount}")
                except Exception as e:
                    await db.rollback()
                    logger.warning(f"Step {name} failed: {e}")

            # RawItem (4h)
            await run_step("raw_items", delete(RawItem).where(RawItem.created_at < (now - timedelta(hours=4))))
            
            # EventCluster (12h)
            # Nullify first
            try:
                cluster_threshold = now - timedelta(hours=12)
                old_clusters_sub = select(EventCluster.id).where(EventCluster.created_at < cluster_threshold)
                null_stmt = update(Item).where(Item.cluster_id.in_(old_clusters_sub)).values(cluster_id=None)
                await db.execute(null_stmt)
                await db.commit()
            except Exception as ne:
                await db.rollback()
                logger.warning(f"Cluster nullify failed: {ne}")
            
            await run_step("event_clusters", delete(EventCluster).where(EventCluster.created_at < (now - timedelta(hours=12))))
            
            # AlertLog (24h)
            await run_step("alert_deliveries", delete(AlertDelivery).where(AlertDelivery.delivered_at < (now - timedelta(hours=24))))
            await run_step("alert_logs", delete(AlertLog).where(AlertLog.triggered_at < (now - timedelta(hours=24))))
            
            # Cache (24h)
            await run_step("analysis_cache", delete(AnalysisCache).where(AnalysisCache.created_at < (now - timedelta(hours=24))))

            # --- 3. VACUUM ANALYZE ---
            logger.info("--- TRIGGERING VACUUM ANALYZE ---")
            for table in ["trend_signals", "raw_items", "event_clusters", "analysis_cache"]:
                try:
                    # VACUUM cannot run inside a transaction block in some drivers, 
                    # but with SQLAlchemy text() and autocommit-like behavior it usually works if we commit first.
                    await db.execute(text(f"VACUUM ANALYZE {table}"))
                    logger.info(f"VACUUM ANALYZE {table} DONE")
                except Exception as ve:
                    logger.warning(f"VACUUM ANALYZE {table} skipped: {ve}")
            
            # --- 4. POST-DIAGNOSTICS ---
            diag_after = await get_table_diagnostics(db)
            results["diagnostics_after"] = diag_after
            size_after = await get_db_size_mb(db)
            results["size_after"] = size_after
            results["success"] = True
            
            logger.info(f"DB Size AFTER cleanup: {size_after} MB")
            logger.info(f"Space recovered: {round(size_before - size_after, 2)} MB")
            return results

        except Exception as e:
            await db.rollback()
            results["error"] = str(e)
            logger.error(f"EMERGENCY CLEANUP FATAL ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return results

if __name__ == "__main__":
    asyncio.run(emergency_cleanup())
