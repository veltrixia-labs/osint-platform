import asyncio
import os
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete, func, text
from db.database import AsyncSessionLocal, get_db_size_mb
from db.models import RawItem, Item, ItemTopic, AlertLog, AlertDelivery, AnalyticsEvent, SecurityLog, AnalysisCache, Report, EventCluster

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("emergency_cleanup")

async def emergency_cleanup():
    logger.info("--- EMERGENCY DATABASE CLEANUP START ---")
    results = {"success": False, "counts": {}, "size_before": 0, "size_after": 0, "error": None}
    
    async with AsyncSessionLocal() as db:
        try:
            # Log DB size before
            size_before = await get_db_size_mb(db)
            results["size_before"] = size_before
            logger.info(f"DB Size BEFORE cleanup: {size_before} MB")
            
            now = datetime.now(timezone.utc)
            
            # --- PRIORITY 1: Raw Items (Aggressive - 1 day) ---
            raw_threshold = now - timedelta(days=1)
            logger.info(f"[P1] Targeting RawItem older than {raw_threshold}")
            raw_stmt = delete(RawItem).where(RawItem.created_at < raw_threshold)
            res = await db.execute(raw_stmt)
            results["counts"]["raw_items"] = res.rowcount
            logger.info(f"[P1] Deleted {res.rowcount} raw_items")
            
            # --- PRIORITY 2: Event Clusters (Aggressive - 3 days) ---
            # We must NULLify cluster_id in Item first because of ForeignKey
            cluster_threshold = now - timedelta(days=3)
            logger.info(f"[P2] Targeting EventCluster older than {cluster_threshold}")
            
            # Subquery for clusters to delete
            old_clusters_sub = select(EventCluster.id).where(EventCluster.created_at < cluster_threshold)
            
            # NULLify items
            from sqlalchemy import update
            null_stmt = update(Item).where(Item.cluster_id.in_(old_clusters_sub)).values(cluster_id=None)
            res_null = await db.execute(null_stmt)
            logger.info(f"[P2] Nullified cluster_id for {res_null.rowcount} items")
            
            # Delete clusters
            cluster_del_stmt = delete(EventCluster).where(EventCluster.created_at < cluster_threshold)
            res_cl = await db.execute(cluster_del_stmt)
            results["counts"]["event_clusters"] = res_cl.rowcount
            logger.info(f"[P2] Deleted {res_cl.rowcount} event_clusters")

            # --- PRIORITY 3: Alert Logs & Deliveries (3 days) ---
            alert_threshold = now - timedelta(days=3)
            logger.info(f"[P3] Targeting AlertLog/Delivery older than {alert_threshold}")
            # Deliveries first
            del_stmt = delete(AlertDelivery).where(AlertDelivery.delivered_at < alert_threshold)
            res = await db.execute(del_stmt)
            results["counts"]["alert_deliveries"] = res.rowcount
            logger.info(f"[P3] Deleted {res.rowcount} alert_deliveries")
            
            log_stmt = delete(AlertLog).where(AlertLog.triggered_at < alert_threshold)
            res = await db.execute(log_stmt)
            results["counts"]["alert_logs"] = res.rowcount
            logger.info(f"[P3] Deleted {res.rowcount} alert_logs")

            # --- PRIORITY 4: Items & Cache (14 days, Protect Strategic Summaries) ---
            item_threshold = now - timedelta(days=14)
            logger.info(f"[P4] Targeting Items older than {item_threshold}")
            
            # Cascade-like manual cleanup
            cache_stmt = delete(AnalysisCache).where(AnalysisCache.created_at < item_threshold)
            res = await db.execute(cache_stmt)
            logger.info(f"[P3] Deleted {res.rowcount} analysis_cache entries")

            it_stmt = delete(ItemTopic).where(ItemTopic.created_at < item_threshold)
            res = await db.execute(it_stmt)
            logger.info(f"[P3] Deleted {res.rowcount} item_topics")

            item_stmt = delete(Item).where(Item.created_at < item_threshold)
            res = await db.execute(item_stmt)
            logger.info(f"[P3] Deleted {res.rowcount} items")

            # --- PRIORITY 4: Reports (Non-essential, 30 days) ---
            # Protect Strategic Reports (Weekly/Monthly)
            # Delete Daily/Event-driven older than 30 days
            persistent_types = ["weekly_global", "monthly_global", "weekly_global_ja", "monthly_global_ja"]
            logger.info(f"[P4] Targeting non-essential reports older than 30 days")
            report_stmt = delete(Report).where(
                Report.created_at < (now - timedelta(days=30)),
                Report.report_type.notin_(persistent_types)
            )
            res = await db.execute(report_stmt)
            logger.info(f"[P4] Deleted {res.rowcount} non-essential reports")

            # Final check - delete analytics events older than 7 days
            logs_threshold = now - timedelta(days=7)
            a_stmt = delete(AnalyticsEvent).where(AnalyticsEvent.created_at < logs_threshold)
            await db.execute(a_stmt)
            s_stmt = delete(SecurityLog).where(SecurityLog.created_at < logs_threshold)
            await db.execute(s_stmt)

            await db.commit()
            logger.info("--- EMERGENCY CLEANUP COMMITTED ---")
            
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
            return results

if __name__ == "__main__":
    asyncio.run(emergency_cleanup())
