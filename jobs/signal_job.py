import asyncio
import gc
import logging
import json
import os
import resource
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from db.database import AsyncSessionLocal
from db.models import Item, ItemTopic, SignalRanking, AnalysisCache, TrendSignal
from llm.client import generate_analysis
from processor.lightweight_topic import is_non_strategic_noise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
# Shorter lookback + item cap keeps clustering O(n^2) bounded on Render.
SIGNAL_LOOKBACK_HOURS = int(os.getenv("SIGNAL_LOOKBACK_HOURS", "168"))  # 7 days
MAX_CLUSTERING_ITEMS = int(os.getenv("SIGNAL_MAX_CLUSTERING_ITEMS", "400"))
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

VALID_STRATEGIC_TOPICS = {
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
}

SINGLETON_RESCUE_TOPICS = {
    "ai_semiconductor_intelligence",
    "supply_chain_intelligence",
}
SINGLETON_RESCUE_CAP = 3          # max new rescue signals per topic per cycle
SINGLETON_RESCUE_LOOKBACK_HOURS = 24
SINGLETON_RESCUE_DEDUP_HOURS = 48  # don't re-rescue an item already rescued recently


def _item_has_valid_source_url(item: Item) -> bool:
    """Clusters without at least one http(s) URL are dropped before TrendSignal creation."""
    raw = (getattr(item, "source_url", None) or "").strip()
    if not raw:
        return False
    low = raw.lower()
    return low.startswith("http://") or low.startswith("https://")


def _cluster_has_source_url(items: List[Item]) -> bool:
    return any(_item_has_valid_source_url(it) for it in items)


def normalize_strategic_topic(raw_topic=None, source_group=None, title="", summary=""):
    """Resolve an item's strategic topic with the FULL ingest-gate protections.

    Passes the real title (enables the title-anchored minimum-signal rule) and
    `strict=True` (drops noise / no-signal to None). Returns None when nothing
    classifies — there is NO `global_market_intelligence` fallback: the caller
    MUST skip a None cluster rather than resurrect noise as a MARKET alert."""
    from processor.lightweight_topic import infer_topic_from_text

    text = f"{title or ''} {summary or ''}".strip()
    return infer_topic_from_text(
        text,
        title=title or None,
        raw_topic=raw_topic,
        source_group=source_group,
        strict=True,
    )


def _resolve_cluster_topic(items: List[Item]):
    """Derive a cluster's topic from the MAJORITY of its items, not items[0].

    A single stale/ghost item can no longer hijack a cluster's domain: we take a
    reliability-weighted vote over the members' categories, use the winner as the
    `raw_topic`, and pick the highest-reliability item IN that majority as the
    representative (its title/text drives the alert + the strict re-eval). Returns
    (strategic_internal_topic_or_None, representative_item)."""
    from collections import Counter

    votes: Counter = Counter()
    for it in items:
        cat = (it.category or "").strip()
        if cat:
            votes[cat] += float(it.reliability_weight or 1.0)

    representative = items[0]
    majority_cat = None
    if votes:
        majority_cat = votes.most_common(1)[0][0]
        matching = [it for it in items if (it.category or "").strip() == majority_cat]
        if matching:
            representative = max(matching, key=lambda it: float(it.reliability_weight or 1.0))

    topic = normalize_strategic_topic(
        raw_topic=majority_cat,
        source_group=representative.source_group,
        title=representative.title or "",
        summary=representative.summary or "",
    )
    return topic, representative

from analysis.clustering import cluster_items
from analysis.signal_engine import run_signal_engine
from sqlalchemy import delete

async def generate_rankings_for_type(db: AsyncSession, signal_type: str, filter_topic: str | None = None):
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=SIGNAL_LOOKBACK_HOURS)
    
    # 1. Fetch Candidates (recency window + cap before O(n^2) clustering)
    stmt = select(Item).where((Item.published_at == None) | (Item.published_at >= start_time))
    if filter_topic:
        # Check topic via ItemTopic or rough_category
        stmt = stmt.where((Item.category == filter_topic) | (Item.rough_category == filter_topic))
    stmt = stmt.order_by(desc(Item.created_at)).limit(MAX_CLUSTERING_ITEMS)

    candidates = (await db.execute(stmt)).scalars().all()
    if not candidates:
        logger.info(f"No candidates for {signal_type} (lookback={SIGNAL_LOOKBACK_HOURS}h)")
        return
    logger.info(
        f"[SIGNAL] {signal_type}: clustering up to {len(candidates)} items "
        f"(lookback={SIGNAL_LOOKBACK_HOURS}h, cap={MAX_CLUSTERING_ITEMS})"
    )

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
    
    # 3. Bulk Fetch Clusters and Items to avoid N+1 problem (Fix v1.6.4)
    from analysis.signal_engine import calculate_cluster_signal
    from db.models import EventCluster
    
    cluster_stmt = (
        select(EventCluster).where(EventCluster.created_at >= start_time).execution_options(yield_per=500)
    )
    clusters = [c async for c in await db.stream_scalars(cluster_stmt)]

    if not clusters:
        logger.info(
            f"[SIGNAL] No clusters found in last {SIGNAL_LOOKBACK_HOURS}h for {signal_type}"
        )
        return

    # Stream the items for these clusters in 500-row partitions STRAIGHT INTO the
    # per-cluster grouping — avoids buffering the whole item join result as a
    # second full list alongside the grouped dict.
    from collections import defaultdict
    cluster_ids = [c.id for c in clusters]
    items_by_cluster = defaultdict(list)
    item_stmt = select(Item).where(Item.cluster_id.in_(cluster_ids)).execution_options(yield_per=500)
    async for it in await db.stream_scalars(item_stmt):
        items_by_cluster[it.cluster_id].append(it)

    final_scored_pool = []
    logger.info(f"[SIGNAL] Scoring {len(clusters)} clusters for {signal_type}...")
    
    for cluster in clusters:
        cluster_items_list = items_by_cluster.get(cluster.id, [])
        if not cluster_items_list:
            continue
            
        score = await calculate_cluster_signal(cluster, cluster_items_list)
        # Use the representative item for ranking pool
        final_scored_pool.append((score, cluster_items_list))

    # 4. Rank and Store — only clusters with ≥1 valid source URL (Alert Manager expects evidence).
    final_scored_pool.sort(key=lambda x: x[0], reverse=True)
    top_items = []
    skipped_no_url = 0
    for score, items in final_scored_pool:
        if not _cluster_has_source_url(items):
            skipped_no_url += 1
            continue
        top_items.append((score, items))
        if len(top_items) >= 10:
            break
    if skipped_no_url:
        logger.info(
            f"[SIGNAL] {signal_type}: skipped {skipped_no_url} clusters with no valid source_url"
        )
    if not top_items:
        logger.info(f"[SIGNAL] {signal_type}: no clusters left after source-url filter; skipping rankings")
        await db.execute(delete(SignalRanking).where(SignalRanking.signal_type == signal_type))
        await db.commit()
        return

    # Resolve each cluster's topic by MAJORITY vote and DROP clusters that strict-eval
    # to None or are non-strategic noise — no MARKET-fallback resurrection of clutter.
    resolved = []
    dropped = 0
    for score, items in top_items:
        topic, representative = _resolve_cluster_topic(items)
        text = f"{representative.title or ''} {representative.summary or ''}".strip()
        if topic is None or is_non_strategic_noise(text):
            dropped += 1
            continue
        resolved.append((score, items, topic, representative))
    if dropped:
        logger.info(f"[SIGNAL] {signal_type}: dropped {dropped} cluster(s) as None/noise (no MARKET fallback)")

    # Always clear stale rankings for this type first.
    await db.execute(delete(SignalRanking).where(SignalRanking.signal_type == signal_type))

    if not resolved:
        logger.info(f"[SIGNAL] {signal_type}: no clusters left after topic/noise filter; skipping rankings")
        await db.commit()
        return

    for score, items, topic, representative in resolved:
        sig = TrendSignal(
            created_at=datetime.now(timezone.utc),
            topic=topic,
            trend_type="risk_acceleration",
            target_label=representative.title,
            intensity_score=float(score),
            metrics_json={
                "baseline": 0.0,
                "recent": float(score),
                "delta": float(score),
                "supporting_cluster_count": len(items),
                "cluster_id": str(representative.cluster_id) if representative.cluster_id else None,
                "supporting_events": [item.title for item in items[:10]]
            }
        )
        db.add(sig)

    for rank, (score, items, topic, representative) in enumerate(resolved, 1):
        db.add(SignalRanking(
            signal_type=signal_type,
            period_start=start_time,
            period_end=now,
            rank=rank,
            item_id=representative.id,
            score=float(score)
        ))

    await db.commit()
    logger.info(f"Rankings updated for {signal_type}: {len(resolved)} items ranked from {len(clusters)} source clusters.")

async def generate_singleton_rescue_signals(db: AsyncSession):
    """Flag-gated (ENABLE_SINGLETON_RESCUE): turn a small capped set of
    un-clustered (cluster_id IS NULL) items in sparse strategic topics into
    marker-tagged TrendSignals so alert_manager can importance-score them.
    No LLM calls here. OFF => no-op."""
    import os
    if os.getenv("ENABLE_SINGLETON_RESCUE", "false").lower() != "true":
        return
    now = datetime.now(timezone.utc)
    item_window = now - timedelta(hours=SINGLETON_RESCUE_LOOKBACK_HOURS)
    dedup_window = now - timedelta(hours=SINGLETON_RESCUE_DEDUP_HOURS)

    # IDs already rescued recently (read metrics_json marker)
    prior = (await db.execute(
        select(TrendSignal.metrics_json).where(TrendSignal.created_at >= dedup_window)
    )).scalars().all()
    rescued_ids = {
        m.get("rescued_item_id") for m in prior
        if isinstance(m, dict) and m.get("singleton_rescue")
    }

    created = 0
    for topic in sorted(SINGLETON_RESCUE_TOPICS):
        stmt = (
            select(Item)
            .where(
                Item.category == topic,
                Item.cluster_id == None,          # noqa: E711  — true singleton
                Item.created_at >= item_window,
            )
            .order_by(desc(Item.created_at))
            .limit(50)                            # small scan window, filter below
        )
        cands = (await db.execute(stmt)).scalars().all()
        n = 0
        for it in cands:
            if n >= SINGLETON_RESCUE_CAP:
                break
            if str(it.id) in rescued_ids or it.id in rescued_ids:
                continue
            if not _item_has_valid_source_url(it):
                continue
            sig = TrendSignal(
                created_at=now,
                topic=topic,
                trend_type="risk_acceleration",
                target_label=it.title,
                intensity_score=0.0,              # honest: no cluster corroboration
                metrics_json={
                    "baseline": 0.0, "recent": 0.0, "delta": 0.0,
                    "supporting_cluster_count": 1,
                    "cluster_id": None,
                    "supporting_events": [it.title],   # exact-title evidence fallback
                    "singleton_rescue": True,
                    "rescued_item_id": str(it.id),
                },
            )
            db.add(sig)
            n += 1
            created += 1
        if n:
            logger.info(f"[RESCUE] {topic}: created {n} singleton rescue signal(s)")
    if created:
        await db.commit()

async def run_signal(db: AsyncSession):
    logger.info("Starting High-Efficiency Signal Job")
    for signal_type, topic_code in TOPIC_SIGNAL_TYPES:
        await generate_rankings_for_type(db, signal_type, filter_topic=topic_code)
        # Release the per-topic working set (up to MAX_CLUSTERING_ITEMS ORM rows
        # in the identity map + the O(n^2) clustering buffers) before the next
        # topic, so peak RSS stays flat across all 7 topics instead of
        # accumulating toward the 512MB ceiling. Placed here (not inside
        # generate_rankings_for_type) so it runs after EVERY topic regardless of
        # that function's several early returns.
        db.expire_all()
        gc.collect()
    await generate_singleton_rescue_signals(db)
    logger.info(f"[MEM] run_signal end peak_rss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0:.0f}MB")
    logger.info("Signal job finished.")

if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_signal(session)
    asyncio.run(main())