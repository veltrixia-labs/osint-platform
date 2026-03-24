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
        LIMIT 10;
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
        "error": None
    }
    
    async with AsyncSessionLocal() as db:
        try:
            # 0. Table Diagnostics Before
            diag_before = await get_table_diagnostics(db)
            results["diagnostics_before"] = diag_before
            logger.info("--- TABLE DIAGNOSTICS (BEFORE) ---")
            for table in diag_before:
                logger.info(f"Table: {table['table_name']}, Total: {table['total_size']}, Rows: {table['estimate_rows']}")

            # Log DB size before
            size_before = await get_db_size_mb(db)
            results["size_before"] = size_before
            logger.info(f"DB Size BEFORE cleanup: {size_before} MB")
            
            now = datetime.now(timezone.utc)
            
            # --- PRIORITY 1: Raw Items (High Aggression - 4 hours) ---
            raw_threshold = now - timedelta(hours=4)
            logger.info(f"[P1] Targeting RawItem older than {raw_threshold}")
            raw_stmt = delete(RawItem).where(RawItem.created_at < raw_threshold)
            res = await db.execute(raw_stmt)
            results["counts"]["raw_items"] = res.rowcount
            logger.info(f"[P1] Deleted {res.rowcount} raw_items")
            
            # --- PRIORITY 2: Event Clusters (High Aggression - 12 hours) ---
            cluster_threshold = now - timedelta(hours=12)
            logger.info(f"[P2] Targeting EventCluster older than {cluster_threshold}")
            
            old_clusters_sub = select(EventCluster.id).where(EventCluster.created_at < cluster_threshold)
            null_stmt = update(Item).where(Item.cluster_id.in_(old_clusters_sub)).values(cluster_id=None)
            res_null = await db.execute(null_stmt)
            logger.info(f"[P2] Nullified cluster_id for {res_null.rowcount} items")
            
            cluster_del_stmt = delete(EventCluster).where(EventCluster.created_at < cluster_threshold)
            res_cl = await db.execute(cluster_del_stmt)
            results["counts"]["event_clusters"] = res_cl.rowcount
            logger.info(f"[P2] Deleted {res_cl.rowcount} event_clusters")

            # --- PRIORITY 3: Alert Logs & Deliveries (24 hours) ---
            alert_threshold = now - timedelta(hours=24)
            logger.info(f"[P3] Targeting AlertLog/Delivery older than {alert_threshold}")
            del_stmt = delete(AlertDelivery).where(AlertDelivery.delivered_at < alert_threshold)
            res = await db.execute(del_stmt)
            results["counts"]["alert_deliveries"] = res.rowcount
            
            log_stmt = delete(AlertLog).where(AlertLog.triggered_at < alert_threshold)
            res = await db.execute(log_stmt)
            results["counts"]["alert_logs"] = res.rowcount
            logger.info(f"[P3] Deleted {res.rowcount} alert entries")

            # --- PRIORITY 4: Cache & Topics (24 hours) ---
            cache_threshold = now - timedelta(hours=24)
            logger.info(f"[P4] Targeting Cache older than {cache_threshold}")
            
            cache_stmt = delete(AnalysisCache).where(AnalysisCache.created_at < cache_threshold)
            res = await db.execute(cache_stmt)
            results["counts"]["analysis_cache"] = res.rowcount
            logger.info(f"[P4] Deleted {res.rowcount} cache entries")

            # --- COMMIT ---
            await db.commit()
            logger.info("--- EMERGENCY CLEANUP COMMITTED ---")

            # --- VACUUM ANALYZE ---
            # Trigger internal space reuse without blocking
            logger.info("--- TRIGGERING VACUUM ANALYZE ---")
            try:
                # We do them one by one
                for table in ["raw_items", "event_clusters", "items", "analysis_cache", "alert_logs"]:
                    await db.execute(text(f"VACUUM ANALYZE {table}"))
                logger.info("--- VACUUM ANALYZE COMPLETED ---")
            except Exception as ve:
                logger.warning(f"VACUUM ANALYZE encountered an issue (non-fatal): {ve}")
            
            # 0. Table Diagnostics After
            diag_after = await get_table_diagnostics(db)
            results["diagnostics_after"] = diag_after
            logger.info("--- TABLE DIAGNOSTICS (AFTER) ---")
            for table in diag_after:
                logger.info(f"Table: {table['table_name']}, Total: {table['total_size']}, Rows: {table['estimate_rows']}")

            # Log DB size after
            size_after = await get_db_size_mb(db)
            results["size_after"] = size_after
            results["success"] = True
            
            logger.info(f"DB Size AFTER cleanup: {size_after} MB")
            logger.info(f"Space recovered: {round(size_before - size_after, 2)} MB")
            return results

        except Exception as e:
            await db.rollback()
            results["error"] = str(e)
            logger.error(f"EMERGENCY CLEANUP FAILED: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return results

if __name__ == "__main__":
    asyncio.run(emergency_cleanup())
