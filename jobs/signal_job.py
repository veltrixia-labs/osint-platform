import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import Item, ItemTopic, SignalRanking, AnalysisCache
from llm.client import generate_analysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
BATCH_SIZE = 5
PROMPT_VERSION = "v2_batch_signal"
CACHE_TTL_DAYS = 3

TOPIC_SIGNAL_TYPES = [
    ("Top 10 Global Risk Signals", None),
    ("Top 10 Energy Resource Risk Signals", "energy_resource_risk"),
    ("Top 10 Global Market Intelligence Signals", "global_market_intelligence"),
    ("Top 10 Crypto Geopolitics Signals", "crypto_geopolitics"),
    ("Top 10 AI Semiconductor Intelligence Signals", "ai_semiconductor_intelligence"),
    ("Top 10 Defense Technology Signals", "defense_technology"),
    ("Top 10 Supply Chain Intelligence Signals", "supply_chain_intelligence"),
]

from analysis.clustering import cluster_items
from analysis.signal_engine import run_signal_engine
from sqlalchemy import delete

async def generate_rankings_for_type(db: AsyncSession, signal_type: str, filter_topic: str | None = None):
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=1)
    
    # 1. Fetch Candidates
    stmt = select(Item).where(Item.published_at >= start_time)
    if filter_topic:
        # Check topic via ItemTopic or rough_category
        stmt = stmt.where((Item.category == filter_topic) | (Item.rough_category == filter_topic))
    
    candidates = (await db.execute(stmt)).scalars().all()
    if not candidates:
        logger.info(f"No candidates for {signal_type}")
        return

    # 2. Clustering (Non-LLM)
    # Note: cluster_items handles DB updates for cluster_id
    metrics = await cluster_items(db, candidates)
    
    # 3. Rule-Based Signal Scoring (Non-LLM)
    # We group by cluster_id for scoring
    clusters_with_items = {}
    for it in candidates:
        if it.cluster_id:
            # Re-fetch cluster for the instance if needed, or assume it's in a dict
            # For simplicity, we'll re-calculate or fetch.
            # Here we'll just use the engine logic on groups
            pass

    # Actually, run_signal_engine expects a dict of {Cluster: [Items]}
    # Let's re-fetch clusters or just use the items directly for scoring logic
    from analysis.signal_engine import calculate_cluster_signal
    from db.models import EventCluster
    
    cluster_stmt = select(EventCluster).where(EventCluster.created_at >= now - timedelta(hours=24))  # [Fix v1.6.3] Expanded from 1h to 24h to capture backlog-processed clusters
    clusters = (await db.execute(cluster_stmt)).scalars().all()
    
    final_scored_pool = []
    for cluster in clusters:
        it_stmt = select(Item).where(Item.cluster_id == cluster.id)
        cluster_items_list = (await db.execute(it_stmt)).scalars().all()
        
        score = await calculate_cluster_signal(cluster, cluster_items_list)
        # Use the representative item for ranking pool
        if cluster_items_list:
            final_scored_pool.append((score, cluster_items_list[0]))

    # 4. Rank and Store
    final_scored_pool.sort(key=lambda x: x[0], reverse=True)
    top_items = final_scored_pool[:10]
    
    # Clear existing rankings for this type
    await db.execute(delete(SignalRanking).where(SignalRanking.signal_type == signal_type))
    
    for rank, (score, item) in enumerate(top_items, 1):
        db.add(SignalRanking(
            signal_type=signal_type,
            period_start=start_time,
            period_end=now,
            rank=rank,
            item_id=item.id,
            score=float(score)
        ))
        
    await db.commit()
    logger.info(f"Rankings updated for {signal_type}: {len(top_items)} clusters.")

async def run_signal(db: AsyncSession):
    logger.info("Starting High-Efficiency Signal Job")
    for signal_type, topic_code in TOPIC_SIGNAL_TYPES:
        await generate_rankings_for_type(db, signal_type, filter_topic=topic_code)
    logger.info("Signal job finished.")

if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_signal(session)
    asyncio.run(main())


if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_signal(session)
    asyncio.run(main())
