import asyncio
import hashlib
import json
import logging
import os
import yaml
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import AsyncSessionLocal
from db.models import RawItem, SourceRegistry
import feedparser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_sources_from_yaml() -> list[dict]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yaml_path = os.path.join(base_dir, "config", "rss_sources.yaml")
    if not os.path.exists(yaml_path):
        logger.error(f"rss_sources.yaml not found at {yaml_path}")
        return []
    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return [src for src in config.get("sources", []) if src.get("enabled", True)]


async def get_enabled_sources_from_db(db: AsyncSession) -> list[SourceRegistry]:
    stmt = select(SourceRegistry).where(SourceRegistry.enabled == True)
    return (await db.execute(stmt)).scalars().all()


async def sync_sources_to_db(db: AsyncSession, sources: list[dict]):
    for src in sources:
        stmt = select(SourceRegistry).where(SourceRegistry.source_id == src["source_id"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if not existing:
            db.add(SourceRegistry(
                source_id=src["source_id"],
                source_name=src["source_name"],
                source_group=src["source_group"],
                rss_url=src["rss_url"],
                reliability_weight=src["reliability_weight"],
                enabled=src.get("enabled", True)
            ))
    await db.commit()


async def fetch_feed(source: dict) -> list[dict]:
    parsed = await asyncio.to_thread(feedparser.parse, source["rss_url"])
    items = []
    for entry in parsed.entries:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
        })
    return items


async def run_ingest(db: AsyncSession):
    logger.info("Starting ingest job")
    
    yaml_sources = load_sources_from_yaml()
    if not yaml_sources:
        logger.error("No sources found. Aborting ingest.")
        return
    
    await sync_sources_to_db(db, yaml_sources)
    
    for src in yaml_sources:
        source_id = src["source_id"]
        try:
            items = await fetch_feed(src)
            logger.info(f"Fetched {len(items)} items from {source_id}")

            new_count = 0
            for item in items:
                payload_str = json.dumps(item, sort_keys=True)
                payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

                stmt = select(RawItem).where(RawItem.payload_hash == payload_hash)
                exists = (await db.execute(stmt)).scalar_one_or_none()

                if not exists:
                    raw = RawItem(
                        fetched_at=datetime.now(timezone.utc),
                        source_system=source_id,
                        source_endpoint=src["rss_url"],
                        source_id=source_id,
                        source_group=src["source_group"],
                        reliability_weight=src["reliability_weight"],
                        payload_json=item,
                        payload_hash=payload_hash
                    )
                    db.add(raw)
                    new_count += 1

            await db.commit()
            logger.info(f"Inserted {new_count} new items for {source_id}")

        except Exception as e:
            logger.error(f"Error fetching from {source_id}: {e}")
            # Individual feed error does NOT stop the whole ingest loop
            continue

    logger.info("Finished ingest job")


if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_ingest(session)
    asyncio.run(main())
