"""
LLM batch classification (DeepSeek). Not invoked by jobs/main_scheduler pipeline.

Standard Alert Stream uses processor.normalize + keyword topics (lightweight_topic)
and rule-based signal_engine scoring only. Run this module from Expert/report jobs
or manual scripts when LLM categorization is required.
"""
import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import not_
from db.models import Item, Topic, ItemTopic, AnalysisCache
from llm.client import generate_analysis

logger = logging.getLogger(__name__)

# --- Constants & Config ---
MAX_TOP_K_TOTAL = 30
CATEGORY_QUOTA = 10
BATCH_SIZE = 10
CACHE_TTL_DAYS = 3
PROMPT_VERSION = "v2_batch_classify_v3"

INITIAL_TOPICS = [
    {"code": "energy_resource_risk", "en": "Energy & Resource Risk", "keywords": ["oil", "crude", "OPEC", "LNG", "natural gas", "uranium", "mining", "energy"]},
    {"code": "global_market_intelligence", "en": "Global Market Intelligence", "keywords": ["fed", "interest rate", "inflation", "recession", "gdp", "stocks", "nasdaq", "bond", "yield"]},
    {"code": "crypto_geopolitics", "en": "Crypto & Regulatory Geopolitics", "keywords": ["bitcoin", "ethereum", "crypto", "blockchain", "defi", "stablecoin", "cbdc", "sec", "regulation"]},
    {"code": "ai_semiconductor_intelligence", "en": "AI & Semiconductor Intelligence", "keywords": ["ai", "nvidia", "tsmc", "intel", "semiconductor", "chip", "llm", "export control"]},
    {"code": "defense_technology", "en": "Defense & Security Technology", "keywords": ["war", "military", "missile", "drone", "defense", "nato", "sanction", "cyber", "espionage"]},
    {"code": "supply_chain_intelligence", "en": "Supply Chain Intelligence", "keywords": ["supply chain", "shipping", "freight", "logistics", "port", "trade", "tariff", "bottleneck"]},
]

async def seed_topics(db: AsyncSession):
    for t in INITIAL_TOPICS:
        stmt = select(Topic).where(Topic.topic_code == t["code"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if not existing:
            db.add(Topic(topic_code=t["code"], topic_name_en=t["en"]))
    await db.commit()

def calculate_lightweight_score(item: Item, matched_kws: List[str]) -> float:
    score = 0.0
    score += min(2.0, len(matched_kws) * 0.4)
    if (item.source_group or "") in {"central_banks", "regulators", "policy_institutions"}:
        score += 1.5
    now = datetime.now(timezone.utc)
    pub_at = item.published_at or item.created_at
    if pub_at.tzinfo is None: pub_at = pub_at.replace(tzinfo=timezone.utc)
    hours_old = (now - pub_at).total_seconds() / 3600
    if hours_old < 12: score += 1.0
    return score

async def pre_filter_and_score(db: AsyncSession, items: List[Item]) -> List[Item]:
    logger.info(f"[Stage 1] Pre-filtering {len(items)} items")
    filtered = []
    seen_titles = set()
    for item in items:
        if not item.title or len(item.title) < 10: continue
        if not item.summary or len(item.summary) < 20: continue
        norm_title = "".join(filter(str.isalnum, item.title.lower()))
        if norm_title in seen_titles: continue
        seen_titles.add(norm_title)
        text = f"{item.title} {item.summary}".lower()
        best_topic = None
        max_kws = 0
        all_matched = []
        for t in INITIAL_TOPICS:
            matched = [kw for kw in t["keywords"] if kw.lower() in text]
            if len(matched) > max_kws:
                max_kws = len(matched)
                best_topic = t["code"]
                all_matched = matched
        item.rough_category = best_topic or "misc"
        item.lightweight_score = calculate_lightweight_score(item, all_matched)
        filtered.append(item)
    return filtered

def select_top_k(items: List[Item]) -> List[Item]:
    items.sort(key=lambda x: x.lightweight_score, reverse=True)
    selected = []
    cat_counts = {}
    for item in items:
        if len(selected) >= MAX_TOP_K_TOTAL: break
        cat = item.rough_category
        count = cat_counts.get(cat, 0)
        if count < CATEGORY_QUOTA or cat == "misc":
            selected.append(item)
            cat_counts[cat] = count + 1
    return selected

async def batch_classify_llm(db: AsyncSession, items: List[Item]) -> Dict[str, Dict]:
    results = {}
    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i+BATCH_SIZE]
        articles_json = []
        for it in batch:
            articles_json.append({
                "id": str(it.id),
                "title": it.title,
                "summary": it.summary[:300],
                "source": it.source_name
            })
            
        system_prompt = (
            "You are an OSINT Risk Analyst. Classify the following articles into one of these categories: "
            f"{[t['code'] for t in INITIAL_TOPICS]}, or 'none'.\n"
            "Return a JSON object with 'results' as a list of objects, each containing:\n"
            "- article_id (exactly as provided)\n- category (code)\n- confidence (0-1)\n- keep (boolean, true if high impact/risk)\n- reason (short)\n"
            "Strictly JSON only."
        )
        user_prompt = f"Articles for classification:\n{json.dumps(articles_json, indent=2)}"
        
        batch_res = await generate_analysis(system_prompt, user_prompt, is_batch=True)
        if batch_res == "__DEGRADED_MODE__" or not isinstance(batch_res, dict):
            # --- Robust Fallback (Keyword-Based) ---
            from sqlalchemy import select
            from db.models import Topic
            topics_stmt = select(Topic)
            all_topics = (await db.execute(topics_stmt)).scalars().all()
            
            for it in batch:
                text = (it.title + " " + (it.summary or "")).lower()
                best_topic = it.rough_category or "none"
                best_score = it.lightweight_score
                
                # Try to improve rough category with specific keywords
                for t in all_topics:
                    kws = t.keywords if isinstance(t.keywords, list) else []
                    if any(kw.lower() in text for kw in kws):
                        best_topic = t.topic_code
                        break
                
                results[str(it.id)] = {
                    "category": best_topic,
                    "confidence": 0.4,
                    "keep": best_score > 3.0 or best_topic != "none",
                    "reason": "Rule-Based Keyword Match (Degraded Mode)"
                }
        else:
            for res_item in batch_res.get("results", []):
                results[res_item["article_id"]] = res_item
    return results

async def run_classify(db: AsyncSession):
    """Classify logic migrated from jobs/classify_job.py."""
    logger.info("Starting Processor Classify Job")
    await seed_topics(db)
    
    now = datetime.now(timezone.utc)

    # --- Bug Fix #1 (Phase 9.1): Select UNANALYZED items, newest first ---
    # Previous: select(Item).limit(100) — always grabbed the oldest 100, ignoring 3,600+ new articles.
    # Fixed:    Only fetch items that have NO entry in analysis_cache, ordered by recency.
    analyzed_ids_subquery = select(AnalysisCache.item_id)
    stmt = (
        select(Item)
        .where(not_(Item.id.in_(analyzed_ids_subquery)))
        .order_by(Item.published_at.desc())
        .limit(100)  # [Opt] Reduced from 500 to prevent OOM/503 on Render low-tier
    )
    all_items = (await db.execute(stmt)).scalars().all()
    logger.info(f"[Classify] Found {len(all_items)} unanalyzed items to process.")
    
    pre_candidates = await pre_filter_and_score(db, all_items)
    
    candidates_to_analyze = []
    for it in pre_candidates:
        cache_stmt = select(AnalysisCache).where(AnalysisCache.item_id == it.id)
        cache = (await db.execute(cache_stmt)).scalar_one_or_none()
        if cache:
            if cache.cache_expires_at and cache.cache_expires_at.replace(tzinfo=timezone.utc) > now:
                it.category = cache.classification_result.get("category")
                continue
        candidates_to_analyze.append(it)
        
    final_candidates = select_top_k(candidates_to_analyze)
    llm_results = await batch_classify_llm(db, final_candidates)
    
    for it in final_candidates:
        res = llm_results.get(str(it.id))
        if res:
            it.category = res.get("category")
            expires = now + timedelta(days=CACHE_TTL_DAYS)
            cache_stmt = select(AnalysisCache).where(AnalysisCache.item_id == it.id)
            cache = (await db.execute(cache_stmt)).scalar_one_or_none()
            if cache:
                cache.classification_result = res
                cache.cache_expires_at = expires
            else:
                db.add(AnalysisCache(
                    item_id=it.id,
                    model_name="batch_v1",
                    prompt_version=PROMPT_VERSION,
                    classification_result=res,
                    cache_expires_at=expires
                ))
            
            if it.category and it.category != "none" and res.get("keep"):
                stmt_it = select(ItemTopic).where(ItemTopic.item_id == it.id, ItemTopic.topic_code == it.category)
                existing_it = (await db.execute(stmt_it)).scalar_one_or_none()
                if not existing_it:
                    db.add(ItemTopic(item_id=it.id, topic_code=it.category, confidence_score=res.get("confidence", 0.5), matched_keywords=[res.get("reason", "LLM Selection")]))

    await db.commit()
    logger.info("Processor Classify finished.")
