import asyncio
import os
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete, func, text
from db.database import AsyncSessionLocal
from db.models import RawItem, Item, ItemTopic, AlertLog, AlertDelivery, AnalyticsEvent, SecurityLog, AnalysisCache, Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("emergency_cleanup")

async def emergency_cleanup():
    logger.info("--- EMERGENCY DATABASE CLEANUP START ---")
    
    async with AsyncSessionLocal() as db:
        try:
            now = datetime.now(timezone.utc)
            
            # --- PRIORITY 1: Raw Items (Aggressive - 2 days) ---
            raw_threshold = now - timedelta(days=2)
            logger.info(f"[P1] Targeting RawItem older than {raw_threshold}")
            raw_stmt = delete(RawItem).where(RawItem.created_at < raw_threshold)
            res = await db.execute(raw_stmt)
            logger.info(f"[P1] Deleted {res.rowcount} raw_items")
            
            # --- PRIORITY 2: Alert Logs & Deliveries (3 days) ---
            alert_threshold = now - timedelta(days=3)
            logger.info(f"[P2] Targeting AlertLog/Delivery older than {alert_threshold}")
            # Deliveries first
            del_stmt = delete(AlertDelivery).where(AlertDelivery.delivered_at < alert_threshold)
            res = await db.execute(del_stmt)
            logger.info(f"[P2] Deleted {res.rowcount} alert_deliveries")
            
            log_stmt = delete(AlertLog).where(AlertLog.triggered_at < alert_threshold)
            res = await db.execute(log_stmt)
            logger.info(f"[P2] Deleted {res.rowcount} alert_logs")

            # --- PRIORITY 3: Items & Cache (7 days, Protect Summary-needed items) ---
            # We PROTECT items that might be needed for monthly/weekly summaries (e.g., last 40 days)
            # But for emergency, we prune anything older than 14 days if really necessary.
            # Here we follow "7 days" as requested but ensure we don't wipe out the whole month's context if we can.
            item_threshold = now - timedelta(days=7)
            logger.info(f"[P3] Targeting Items older than {item_threshold}")
            
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
            
            # 6. Maintenance
            # Note: PostgreSQL requires VACUUM to actually reclaim OS-level disk space quickly in some cases,
            # but on managed DBs like Render, the space is usually marked as reusable immediately.
            try:
                await db.execute(text("VACUUM ANALYZE"))
                logger.info("Maintenance (VACUUM ANALYZE) requested.")
            except Exception as maintenance_e:
                logger.warning(f"Maintenance task failed (often expected on shared PG): {maintenance_e}")

        except Exception as e:
            await db.rollback()
            logger.error(f"EMERGENCY CLEANUP FAILED: {e}")
            raise

if __name__ == "__main__":
    asyncio.run(emergency_cleanup())
