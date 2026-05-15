import asyncio
import json
import logging
import os

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import AlertLog, Item
from jobs.free_alert_feed_generator import build_free_alert_feed_item

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_free_alert_feed():
    async with AsyncSessionLocal() as db:
        from db.models import TrendSignal
        from jobs.alert_manager import AlertManager
        
        # 1. Fetch a fresh TrendSignal to avoid cooldown suppression
        stmt_sig = select(TrendSignal).outerjoin(
            AlertLog, AlertLog.target_label == TrendSignal.target_label
        ).where(AlertLog.id == None).order_by(TrendSignal.created_at.desc()).limit(1)
        sig = (await db.execute(stmt_sig)).scalar_one_or_none()
        
        if not sig:
            logger.info("No TrendSignal found in the DB. Cannot generate a new alert.")
            return
            
        logger.info(f"Triggering AlertManager for TrendSignal: {sig.target_label} (Topic: {sig.topic})")
        
        # Generate new alert (auto-triggers persist_free_alert_feed_item inside)
        await AlertManager.evaluate_and_send(db, [sig])
        await db.commit()

        # 2. Fetch the newly created AlertLog
        stmt_alert = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(1)
        alert_log = (await db.execute(stmt_alert)).scalar_one_or_none()
        
        if not alert_log:
            logger.info("AlertManager failed to create an AlertLog (might be suppressed). Exiting.")
            return

        logger.info(f"Using AlertLog: {alert_log.id} | Label: {alert_log.target_label}")
        logger.info(f"Metadata JSON related_item_ids: {alert_log.metadata_json.get('related_item_ids')}")

        # Verify auto-persistence
        logger.info("Verifying auto-persistence in AlertLog.metadata_json['free_alert']:")
        persisted = alert_log.metadata_json.get("free_alert", {})
        if not persisted:
            logger.error("free_alert was NOT auto-generated in metadata_json!")
            return
            
        persisted_summary = {k: v for k, v in persisted.items() if k != "content_markdown"}
        print(json.dumps(persisted_summary, indent=2))

        # 3. Save the Markdown content
        md_content = persisted.get("content_markdown", "")
        out_path = os.path.join("scratch", "free_alert_feed_sample.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
            
        logger.info(f"Markdown content saved to: {out_path}")





if __name__ == "__main__":
    asyncio.run(test_free_alert_feed())
