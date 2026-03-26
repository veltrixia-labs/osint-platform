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
    
    logger.info(f"[SIGNAL RANKING] Processing: {signal_type} | filter_topic={filter_topic}")
    
    # 1. Fetch Candidates (Items) for this topic
    stmt = select(Item).where(Item.published_at >= start_time)
    if filter_topic:
        # Check topic via ItemTopic or rough_category
        # We join with ItemTopic to be strictly topic-scoped
        stmt = stmt.join(ItemTopic, ItemTopic.item_id == Item.id).where(ItemTopic.topic_code == filter_topic)
    
    candidates = (await db.execute(stmt)).scalars().all()
    if not candidates:
        logger.info(f"No candidates for {signal_type}")
        return

    candidate_ids = [it.id for it in candidates]
    logger.info(f"Found {len(candidates)} candidate items for topic {filter_topic}")

    # 2. Clustering (Non-LLM)
    # cluster_items handles DB updates for cluster_id for these candidates
    metrics = await cluster_items(db, candidates)
    
    # 3. Rule-Based Signal Scoring (Non-LLM)
    from analysis.signal_engine import calculate_cluster_signal
    from db.models import EventCluster
    
    # FIXED: Re-fetch ONLY clusters that contain candidates from this topic
    # This ensures specialized rankings are strictly topic-scoped.
    cluster_stmt = select(EventCluster).where(
        EventCluster.id.in_(
            select(Item.cluster_id).where(Item.id.in_(candidate_ids))
        )
    )
    clusters = (await db.execute(cluster_stmt)).scalars().all()
    
    logger.info(f"Processing {len(clusters)} topic-scoped clusters for {signal_type}")

    final_scored_pool = []
    for cluster in clusters:
        # Fetch items for this cluster that also match the topic (double-check isolation)
        it_stmt = select(Item).where(Item.cluster_id == cluster.id)
        if filter_topic:
            it_stmt = it_stmt.join(ItemTopic, ItemTopic.item_id == Item.id).where(ItemTopic.topic_code == filter_topic)
            
        cluster_items_list = (await db.execute(it_stmt)).scalars().all()
        
        if not cluster_items_list:
            continue
            
        score = await calculate_cluster_signal(cluster, cluster_items_list)
        # Use the representative item for ranking pool
        final_scored_pool.append((score, cluster_items_list[0], cluster.id))

    # 4. Rank and Store
    final_scored_pool.sort(key=lambda x: x[0], reverse=True)
    top_items = final_scored_pool[:10]
    
    # Clear existing rankings for this type
    await db.execute(delete(SignalRanking).where(SignalRanking.signal_type == signal_type))
    
    for rank, (score, item, cluster_id) in enumerate(top_items, 1):
        ranking_entry = SignalRanking(
            signal_type=signal_type,
            period_start=start_time,
            period_end=now,
            rank=rank,
            item_id=item.id,
            score=float(score)
        )
        db.add(ranking_entry)
        logger.info(f"RANK {rank}: Cluster {cluster_id} | Score {score:.2f} | Topic {filter_topic}")
        
    await db.commit()
    logger.info(f"Rankings updated for {signal_type}: {len(top_items)} clusters saved.")

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
