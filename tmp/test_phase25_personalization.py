import asyncio
import uuid
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from db.models import AnalystProfile, AlertLog, TrendSignal, AlertDelivery, Base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from jobs.alert_manager import AlertManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASYNC_DB_URL = "sqlite+aiosqlite:///osint.db"
engine = create_async_engine(ASYNC_DB_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

from db.models import AnalystProfile, AlertLog, TrendSignal, AlertDelivery, Base, Item

async def setup_mock_data(db):
    # Clear existing
    await db.execute(AnalystProfile.__table__.delete())
    await db.execute(AlertDelivery.__table__.delete())
    await db.execute(Item.__table__.delete())
    
    p1 = AnalystProfile(
        id=uuid.uuid4(),
        telegram_chat_id="111111111",
        watch_keywords=["Nuclear"],
        watch_sectors=["energy"],
        min_severity_threshold="watch",
        min_intelligence_threshold=0.4,
        is_active=True
    )
    p2 = AnalystProfile(
        id=uuid.uuid4(),
        telegram_chat_id="222222222",
        watch_keywords=["Cyber"],
        watch_sectors=["technology"],
        min_severity_threshold="critical", # High threshold
        min_intelligence_threshold=0.9,    # Very high threshold
        is_active=True
    )
    db.add_all([p1, p2])
    
    # Mock items for 10 domains
    titles = ["Nuclear Blast 1", "Nuclear Blast 2"]
    for i in range(10):
        it = Item(
            id=uuid.uuid4(),
            title=titles[i % 2],
            dedup_key=f"test-dedup-{i}",
            source_url=f"https://domain{i}.com/news",
            published_at=datetime.now(timezone.utc)
        )
        db.add(it)
        
    await db.commit()
    return p1, p2

async def verify_personalization():
    async with AsyncSessionLocal() as db:
        p1, p2 = await setup_mock_data(db)
        
        # Scenario 1: Nuclear Risk Signal (Matches P1 Watchlist)
        sig1 = TrendSignal(
            id=uuid.uuid4(),
            target_label="Nuclear Escalation in Middle East",
            trend_type="risk_pattern",
            intensity_score=7.0,
            metrics_json={"supporting_cluster_count": 5, "supporting_events": ["Event 1", "Event 2"]}
        )
        
        logger.info("\n--- Scenario 1: Nuclear Signal (Matches P1) ---")
        await AlertManager.evaluate_and_send(db, [sig1])
        
        deliveries = (await db.execute(select(AlertDelivery))).scalars().all()
        for d in deliveries:
            profile_name = "P1" if str(d.analyst_id) == str(p1.id) else "P2"
            logger.info(f"Delivery to {profile_name}: {d.status} (Score: {d.relevance_score})")

        # Scenario 2: High-Score Critical Broadcast (Force high score via intensity and domains if possible)
        # Or we can just mock a signal that will pass should_broadcast
        sig2 = TrendSignal(
            id=uuid.uuid4(),
            target_label="MAJOR NUCLEAR EVENT", # Matches Nuclear too
            trend_type="risk_pattern",
            intensity_score=10.0,
            metrics_json={"supporting_cluster_count": 20, "supporting_events": ["Nuclear Blast 1", "Nuclear Blast 2"]}
        )
        # Note: Scorer will give 0.3 (Intens) + 0.3 (Hist approx) + 0.0 (Spike) + 0.0 (Domains mock) = 0.6
        # To hit 0.85, we need spike or domains.
        # Let's mock a spike in the DB for this label.
        prev_sig = TrendSignal(
            id=uuid.uuid4(),
            target_label="MAJOR NUCLEAR EVENT",
            trend_type="risk_pattern",
            intensity_score=2.0,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        db.add(prev_sig)
        await db.commit()
        
        logger.info("\n--- Scenario 2: Critical High-Score Broadcast ---")
        await AlertManager.evaluate_and_send(db, [sig2])
        
        # Check if P2 (Cyber watch, 0.5 threshold) received the Nuclear Broadcast
        # sig2 score will be high due to spike (10 - 2 = 8 delta)
        sig2_deliveries = (await db.execute(select(AlertDelivery).join(AlertLog).where(AlertLog.target_label == "MAJOR NUCLEAR EVENT"))).scalars().all()
        for d in sig2_deliveries:
            profile_name = "P1" if str(d.analyst_id) == str(p1.id) else "P2"
            logger.info(f"Final Broadcast to {profile_name}: {d.status} (Relevance: {d.relevance_score})")

        await db.commit()

if __name__ == "__main__":
    asyncio.run(verify_personalization())
