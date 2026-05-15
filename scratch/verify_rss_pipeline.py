import asyncio
import logging
import os
import json
from datetime import datetime, timezone
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import RawItem, Item, TrendSignal, AlertLog, Topic
from jobs.ingest_job import fetch_feed
from processor.normalize import run_normalize
from processor.classify import run_classify
from jobs.signal_job import run_signal
from jobs.trend_analyze_job import run_trend_analysis
from jobs.alert_manager import run_alert_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PipelineVerify")

async def verify_pipeline():
    logger.info("--- Starting Pipeline Verification ---")
    
    # 1. DB Connection Check
    from config.settings import settings
    logger.info(f"Database URL: {settings.database_url}")
    if "osint_platform.db" not in settings.database_url:
        logger.error("DANGER: Not using local SQLite DB. Aborting for safety.")
        return

    async with AsyncSessionLocal() as session:
        # 2. RSS Ingest (Single Item)
        source = {
            "source_id": "bbc_world_test",
            "source_name": "BBC World (Test)",
            "source_group": "global_news",
            "rss_url": "https://feeds.bbci.co.uk/news/world/rss.xml",
            "reliability_weight": 0.90
        }
        
        logger.info(f"Fetching from {source['rss_url']}...")
        try:
            items = await fetch_feed(source)
        except Exception as e:
            logger.error(f"Failed to fetch feed: {e}")
            return
            
        if not items:
            logger.error("No items fetched. Check internet connection or RSS URL.")
            return
        
        # Take only 1 item for test
        test_item = items[0]
        logger.info(f"Test Item: {test_item['title']}")
        
        # Save to RawItem
        raw = RawItem(
            fetched_at=datetime.now(timezone.utc),
            source_system=source["source_id"],
            source_endpoint=source["rss_url"],
            source_id=source["source_id"],
            source_group=source["source_group"],
            reliability_weight=source["reliability_weight"],
            payload_json=test_item,
            payload_hash="test_hash_" + str(datetime.now().timestamp())
        )
        session.add(raw)
        await session.commit()
        await session.refresh(raw)
        logger.info(f"RawItem saved. ID: {raw.id}")

        # 3. Normalize
        logger.info("Running Normalize...")
        await run_normalize(session)
        
        # Check if Item was created
        stmt = select(Item).where(Item.source_id == source["source_id"]).order_by(Item.created_at.desc())
        normalized_item = (await session.execute(stmt)).scalars().first()
        if not normalized_item:
            logger.error("Normalization failed to create an Item.")
            return
        logger.info(f"Item created. ID: {normalized_item.id}, Title: {normalized_item.title}")

        # 4. Classify (Limited to this item)
        logger.info("Running Classify...")
        await run_classify(session)
        
        # Refresh item to see category
        await session.refresh(normalized_item)
        logger.info(f"Item Category: {normalized_item.category}")

        # 5. Signal & Trend
        logger.info("Running Signal Job...")
        await run_signal(session)
        
        logger.info("Running Trend Analysis...")
        await run_trend_analysis(session)
        
        # Check TrendSignal
        sig_stmt = select(TrendSignal).order_by(TrendSignal.created_at.desc())
        latest_sig = (await session.execute(sig_stmt)).scalars().first()
        
        # Manually ensure we have a TrendSignal if logic didn't trigger one for a single item
        if not latest_sig or (datetime.now(timezone.utc) - latest_sig.created_at.replace(tzinfo=timezone.utc)).total_seconds() > 60:
            logger.info("Manually creating TrendSignal for testing Alert Manager...")
            latest_sig = TrendSignal(
                target_label=normalized_item.title,
                topic=normalized_item.category or "global_market_intelligence",
                trend_type="manual_test",
                intensity_score=8.5,
                description="Manual test signal for pipeline verification.",
                metrics_json={"supporting_events": [normalized_item.title]}
            )
            session.add(latest_sig)
            await session.commit()
            await session.refresh(latest_sig)
        
        logger.info(f"TrendSignal: {latest_sig.target_label} (Intensity: {latest_sig.intensity_score})")

        # 6. Alert Manager
        logger.info("Running Alert Manager...")
        await run_alert_manager(session)
        
        # 7. Final Verification
        alert_stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc())
        latest_alert = (await session.execute(alert_stmt)).scalars().first()
        
        if latest_alert:
            logger.info("--- Pipeline Success! ---")
            logger.info(f"Alert Generated: {latest_alert.target_label}")
            logger.info(f"Severity: {latest_alert.severity}")
            evidence = latest_alert.metadata_json.get('evidence_list', [])
            logger.info(f"Evidence List: {json.dumps(evidence, indent=2)}")
            if evidence and 'url' in evidence[0]:
                logger.info(f"Source URL verified: {evidence[0]['url']}")
            else:
                logger.warning("Source URL missing in evidence_list.")
        else:
            logger.error("No AlertLog generated.")

if __name__ == "__main__":
    asyncio.run(verify_pipeline())
