import asyncio
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import select, delete, update
from db.database import AsyncSessionLocal
from db.models import TrendSignal, Item, AlertLog, AlertDelivery, AnalystProfile
from jobs.alert_manager import AlertManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def setup_test_data(db):
    # Cleanup previous test data
    await db.execute(delete(AlertLog).where(AlertLog.target_label.like("TEST_%")))
    await db.execute(delete(TrendSignal).where(TrendSignal.target_label.like("TEST_%")))
    await db.execute(delete(Item).where(Item.title.like("TEST_%")))
    await db.commit()

async def test_exact_match():
    logger.info("--- Testing Case 1: Exact Match ---")
    async with AsyncSessionLocal() as db:
        title = "TEST_EXACT_MATCH_ARTICLE_1"
        item = Item(
            id=uuid.uuid4(),
            title=title,
            source_url="https://test.com/exact",
            dedup_key=f"test_exact_{uuid.uuid4()}"
        )
        db.add(item)
        
        sig = TrendSignal(
            id=uuid.uuid4(),
            trend_type="risk_pattern",
            target_label="TEST_EXACT",
            intensity_score=7.0,
            metrics_json={
                "supporting_events": [title],
                "supporting_events_count": 1
            }
        )
        db.add(sig)
        await db.commit()
        
        await AlertManager.evaluate_and_send(db, [sig])
        await db.commit()
        
        stmt = select(AlertLog).where(AlertLog.target_label == "TEST_EXACT").order_by(AlertLog.triggered_at.desc())
        alert = (await db.execute(stmt)).scalar()
        
        assert alert is not None, "AlertLog should be created"
        assert alert.status == "confirmed", f"Status should be confirmed (got {alert.status})"
        assert alert.metadata_json.get("domain_count", 0) > 0, "Domain count should be > 0"
        logger.info("Case 1 Passed!")

async def test_fallback_match():
    logger.info("--- Testing Case 2: Fallback Match ---")
    async with AsyncSessionLocal() as db:
        # Item title contains label but is not an exact match to 'supporting_events'
        item = Item(
            id=uuid.uuid4(),
            title="TEST_FALLBACK Entity News",
            source_url="https://test.com/fallback",
            dedup_key=f"test_fallback_{uuid.uuid4()}"
        )
        db.add(item)
        
        sig = TrendSignal(
            id=uuid.uuid4(),
            trend_type="risk_pattern",
            target_label="TEST_FALLBACK",
            intensity_score=7.0,
            metrics_json={
                "supporting_events": ["Something else"],
                "supporting_events_count": 1
            }
        )
        db.add(sig)
        await db.commit()
        
        await AlertManager.evaluate_and_send(db, [sig])
        await db.commit()
        
        stmt = select(AlertLog).where(AlertLog.target_label == "TEST_FALLBACK").order_by(AlertLog.triggered_at.desc())
        alert = (await db.execute(stmt)).scalar()
        
        assert alert is not None, "AlertLog should be created"
        assert alert.status == "confirmed", f"Status should be confirmed via fallback (got {alert.status})"
        assert alert.metadata_json.get("domain_count", 0) > 0, "Domain count should be > 0 via fallback"
        logger.info("Case 2 Passed!")

async def test_no_analyst_match():
    logger.info("--- Testing Case 3: No Analyst Match (System-Wide) ---")
    async with AsyncSessionLocal() as db:
        # Temporarily set high thresholds for all analysts to ensure no match
        await db.execute(update(AnalystProfile).values(min_intelligence_threshold=1.0))
        await db.commit()
        
        try:
            # High intensity signal with no analyst keywords matching "TEST_SYSTEMWIDE"
            sig = TrendSignal(
                id=uuid.uuid4(),
                trend_type="risk_pattern",
                target_label="TEST_SYSTEMWIDE",
                intensity_score=9.0,
                metrics_json={
                    "supporting_events": ["No evidence link available"],
                    "supporting_events_count": 1
                }
            )
            db.add(sig)
            await db.commit()
            
            await AlertManager.evaluate_and_send(db, [sig])
            await db.commit()
            
            stmt = select(AlertLog).where(AlertLog.target_label == "TEST_SYSTEMWIDE").order_by(AlertLog.triggered_at.desc())
            alert = (await db.execute(stmt)).scalar()
            
            assert alert is not None, "AlertLog should be created"
            assert alert.is_system_wide is True, "Should be marked as is_system_wide"
            assert alert.status == "pending_evidence", "Should be pending_evidence since no items matched"
            logger.info("Case 3 Passed!")
        finally:
            # Restore thresholds
            await db.execute(update(AnalystProfile).values(min_intelligence_threshold=0.35))
            await db.commit()

async def run_all():
    async with AsyncSessionLocal() as db:
        await setup_test_data(db)
    
    await test_exact_match()
    await test_fallback_match()
    await test_no_analyst_match()
    
    logger.info("All verification tests completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_all())
