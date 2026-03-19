import asyncio
import logging
import feedparser
import aiohttp
from datetime import datetime, timezone
import yaml
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import SourceRegistry, SourceHealthLog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_sources_from_yaml(db: AsyncSession):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yaml_path = os.path.join(base_dir, "config", "rss_sources.yaml")
    
    if not os.path.exists(yaml_path):
        logger.error(f"Config file not found: {yaml_path}")
        return
        
    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    for src in config.get("sources", []):
        stmt = select(SourceRegistry).where(SourceRegistry.source_id == src["source_id"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        
        if existing:
            # Update existing values just in case config changed
            existing.source_name = src["source_name"]
            existing.source_group = src["source_group"]
            existing.rss_url = src["rss_url"]
            existing.reliability_weight = src["reliability_weight"]
            # don't override existing.enabled here if it was auto-disabled by failures
        else:
            new_source = SourceRegistry(
                source_id=src["source_id"],
                source_name=src["source_name"],
                source_group=src["source_group"],
                rss_url=src["rss_url"],
                reliability_weight=src["reliability_weight"],
                enabled=src.get("enabled", True)
            )
            db.add(new_source)
    await db.commit()

async def check_feed(session: aiohttp.ClientSession, source: SourceRegistry) -> tuple[bool, int, str]:
    try:
        async with session.get(source.rss_url, timeout=15) as response:
            if response.status != 200:
                return False, 0, f"HTTP Status {response.status}"
            
            content = await response.text()
            parsed = await asyncio.to_thread(feedparser.parse, content)
            
            if parsed.bozo and parsed.bozo_exception:
                return False, 0, f"Parse error: {str(parsed.bozo_exception)}"
                
            entry_count = len(parsed.entries)
            if entry_count == 0:
                return False, 0, "0 entries parsed"
                
            return True, entry_count, "OK"
    except Exception as e:
        return False, 0, str(e)

async def run_health_check(db: AsyncSession):
    logger.info("Starting RSS health check job")
    await init_sources_from_yaml(db)
    
    stmt = select(SourceRegistry).where(SourceRegistry.enabled == True)
    sources = (await db.execute(stmt)).scalars().all()
    
    now = datetime.now(timezone.utc)
    
    async with aiohttp.ClientSession() as http_session:
        for source in sources:
            success, count, msg = await check_feed(http_session, source)
            
            log_entry = SourceHealthLog(
                source_id=source.source_id,
                checked_at=now,
                success=success,
                entry_count=count,
                error_message=msg if not success else None
            )
            db.add(log_entry)
            
            source.last_checked_at = now
            if success:
                source.last_success_at = now
                source.consecutive_failures = 0
                logger.info(f"[OK] {source.source_id}: {count} entries")
            else:
                source.consecutive_failures += 1
                logger.warning(f"[FAIL] {source.source_id}: {msg}. Failures: {source.consecutive_failures}")
                
                if source.consecutive_failures >= 5:
                    logger.error(f"[DISABLE] Auto-disabling {source.source_id} after {source.consecutive_failures} failures.")
                    source.enabled = False
                    
    await db.commit()
    logger.info("Finished RSS health check job")

if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_health_check(session)
    asyncio.run(main())
