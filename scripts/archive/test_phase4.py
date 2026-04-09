import asyncio
import logging
import uuid
from db.database import AsyncSessionLocal
from processor.impact_discovery import ImpactDiscoveryEngine
from db.models import Stakeholder, TrendSignal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Phase4Test")

async def test_cascading_discovery():
    async with AsyncSessionLocal() as db:
        # 1. Ensure we have stakeholders
        from sqlalchemy.future import select
        stmt = select(Stakeholder)
        stakes = (await db.execute(stmt)).scalars().all()
        if not stakes:
            logger.error("No stakeholders found. Run scripts/setup_phase4_db.py first.")
            return

        logger.info(f"Found {len(stakes)} stakeholders in DB.")

        # 2. Simulate a high-impact signal
        # Topic: AI & Semiconductors
        # Title: US Department of Commerce announces new restrictions on AI chip exports to China.
        test_title = "US Commerce Dept: New Export Restrictions on H100/H200 Chips"
        test_summary = (
            "The BIS is expanding the entity list to include 20 more Chinese AI firms. "
            "NVIDIA and TSMC expected to face immediate compliance hurdles. "
            "Downstream impact likely for cloud providers like AWS and Alibaba."
        )

        engine = ImpactDiscoveryEngine(db)
        logger.info("Running Discovery Engine...")
        
        results = await engine.run_discovery(
            trigger_item_id=uuid.uuid4(),
            title=test_title,
            summary=test_summary
        )

        logger.info("--- DISCOVERY RESULTS ---")
        for r in results:
            stake_name = r.get("entity_name")
            alpha = r.get("impact_alpha")
            reasoning = r.get("reasoning")
            lat = r.get("location_lat")
            logger.info(f"Stakeholder: {stake_name} | Predicted Alpha: {alpha}%")
            logger.info(f"  Reasoning: {reasoning}")
            logger.info(f"  Location Mapping: {lat}")

        if results:
            logger.info("SUCCESS: Cascading impact discovered and logged.")
        else:
            logger.warning("No impacts discovered. Check LLM context/connectivity.")

if __name__ == "__main__":
    asyncio.run(test_cascading_discovery())
