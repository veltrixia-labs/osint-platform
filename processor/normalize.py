import hashlib
import re
import logging
from datetime import datetime, timezone, timedelta
from dateutil import parser as dt_parser
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.models import RawItem, Item

logger = logging.getLogger(__name__)

def normalize_text(text: str) -> str:
    """Removes non-alphanumeric chars and lowercases."""
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

async def run_normalize(db: AsyncSession):
    """
    High-Efficiency Normalize Job migrated from jobs/normalize_job.py.
    Handles Stage 1 normalization: Noise filtering and URL-based deduplication.
    """
    logger.info("Starting Processor Normalize Job")
    
    lookback = datetime.now(timezone.utc) - timedelta(hours=12)
    
    # Efficient selection: Filter by recent created_at AND limit to avoid massive sorts
    stmt = select(RawItem).where(RawItem.created_at > lookback).order_by(RawItem.created_at.desc()).limit(500)
    result = await db.execute(stmt)
    raw_items = result.scalars().all()
    
    metrics = {"normalized": 0, "noise_filtered": 0, "deduped": 0}
    
    for raw in raw_items:
        payload = raw.payload_json
        url = payload.get("link", "")
        title = payload.get("title", "")
        summary = payload.get("summary", "")
        
        if not url or not title:
            continue
            
        # 1. Noise Filter
        if len(title) < 15 or len(summary) < 20: 
            metrics["noise_filtered"] += 1
            continue
            
        # 2. Advanced Dedupe (URL + Normalized Title Hash)
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        title_norm = normalize_text(title)
        title_hash = hashlib.sha256(title_norm.encode('utf-8')).hexdigest()
        
        # Check if item exists (URL or title hash match)
        check_stmt = select(Item).where((Item.dedup_key == url_hash) | (Item.dedup_key == title_hash))
        item_exists = (await db.execute(check_stmt)).scalar_one_or_none()
        
        if not item_exists:
            pub_date_str = payload.get("published", "")
            pub_date = raw.fetched_at
            if pub_date_str:
                try:
                    parsed_date = dt_parser.parse(pub_date_str)
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    pub_date = parsed_date
                except Exception:
                    pass
            
            new_item = Item(
                type="article",
                dedup_key=url_hash,
                published_at=pub_date,
                title=title,
                summary=summary,
                source_name=raw.source_system,
                source_url=url,
                source_id=raw.source_id,
                source_group=raw.source_group,
                reliability_weight=raw.reliability_weight,
                category="news",
                geo={},
                tags={}
            )
            db.add(new_item)
            metrics["normalized"] += 1
        else:
            metrics["deduped"] += 1
            
    await db.commit()
    logger.info(f"Processor Normalize finished. Metrics: {metrics}")
