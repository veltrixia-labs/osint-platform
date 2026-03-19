import asyncio
import yaml
import logging
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from db.database import AsyncSessionLocal
from db.models import SignalRanking, ReportTriggerLog
from article.report_job import run_report_generation
from jobs.threads_post_job import post_to_threads

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_teaser_for_threads(text: str) -> str:
    """Pass-through for the already formatted Threads teaser from Phase 11."""
    return text.strip()

def load_trigger_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "config", "trigger_config.yaml")
    if not os.path.exists(path):
        logger.error(f"Trigger config not found at {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

async def check_cooldown(db: AsyncSession, topic_code: str, cooldown_minutes: int) -> bool:
    """Returns True if the topic is currently in cooldown (recently triggered)."""
    cooldown_threshold = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
    stmt = select(ReportTriggerLog).where(
        ReportTriggerLog.topic_code == topic_code,
        ReportTriggerLog.triggered_at >= cooldown_threshold
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None

async def run_trigger_check(db: AsyncSession):
    logger.info("Starting trigger detector check (English-only)...")
    config = load_trigger_config()
    if not config:
        return

    # 1. Global Check
    global_cfg = config.get("global", {})
    global_threshold = global_cfg.get("score_threshold", 18.0)
    global_cooldown = global_cfg.get("cooldown_minutes", 120)

    recent_threshold = datetime.now(timezone.utc) - timedelta(hours=1)
    
    stmt_global = select(func.max(SignalRanking.score)).where(
        SignalRanking.signal_type == "Top 10 Global Risk Signals",
        SignalRanking.created_at >= recent_threshold
    )
    max_global_score = (await db.execute(stmt_global)).scalar() or 0.0

    if max_global_score >= global_threshold:
        if not await check_cooldown(db, "global", global_cooldown):
            logger.info(f"[TRIGGER] Global signal score {max_global_score} exceeded threshold {global_threshold}")
            teaser, status, msg = await run_report_generation(db, report_type="event_driven_global", period_days=1, topic=None)
            
            # Post to Threads
            threads_text = clean_teaser_for_threads(teaser)
            await post_to_threads(threads_text)
            
            # Log trigger
            db.add(ReportTriggerLog(
                topic_code="global",
                peak_score=max_global_score,
                report_type="event_driven_global"
            ))
            await db.commit()

    # 2. Per-Topic Check
    topics_cfg = config.get("topics", {})
    for topic_code, t_cfg in topics_cfg.items():
        threshold = t_cfg.get("score_threshold", 15.0)
        cooldown = t_cfg.get("cooldown_minutes", 120)

        signal_type_map = {
            "energy_resource_risk": "Top 10 Energy Resource Risk Signals",
            "global_market_intelligence": "Top 10 Global Market Intelligence Signals",
            "crypto_geopolitics": "Top 10 Crypto Geopolitics Signals",
            "ai_semiconductor_intelligence": "Top 10 AI Semiconductor Intelligence Signals",
            "defense_technology": "Top 10 Defense Technology Signals",
            "supply_chain_intelligence": "Top 10 Supply Chain Intelligence Signals",
        }
        
        sig_type = signal_type_map.get(topic_code)
        if not sig_type:
            continue

        stmt_topic = select(func.max(SignalRanking.score)).where(
            SignalRanking.signal_type == sig_type,
            SignalRanking.created_at >= recent_threshold
        )
        max_score = (await db.execute(stmt_topic)).scalar() or 0.0

        if max_score >= threshold:
            if not await check_cooldown(db, topic_code, cooldown):
                logger.info(f"[TRIGGER] Topic '{topic_code}' score {max_score} exceeded threshold {threshold}")
                teaser, status, msg = await run_report_generation(db, report_type=f"event_driven_{topic_code}", period_days=1, topic=topic_code)
                
                # Post to Threads
                threads_text = clean_teaser_for_threads(teaser)
                await post_to_threads(threads_text)
                
                db.add(ReportTriggerLog(
                    topic_code=topic_code,
                    peak_score=max_score,
                    report_type=f"event_driven_{topic_code}"
                ))
                await db.commit()

    logger.info("Trigger detector check finished.")

if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_trigger_check(session)
    asyncio.run(main())
