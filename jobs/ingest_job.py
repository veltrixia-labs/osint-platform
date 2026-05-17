import asyncio
import hashlib
import json
import logging
import os
import uuid
import yaml
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import RawItem, SourceRegistry
import feedparser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HASH_CHUNK_SIZE = int(os.getenv("INGEST_HASH_CHUNK_SIZE", "500"))


def load_sources_from_yaml() -> list[dict]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yaml_path = os.path.join(base_dir, "config", "rss_sources.yaml")
    if not os.path.exists(yaml_path):
        logger.error(f"rss_sources.yaml not found at {yaml_path}")
        return []
    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return [src for src in config.get("sources", []) if src.get("enabled", True)]


async def sync_sources_to_db(db: AsyncSession, sources: list[dict]):
    for src in sources:
        stmt = select(SourceRegistry).where(SourceRegistry.source_id == src["source_id"])
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if not existing:
            db.add(
                SourceRegistry(
                    source_id=src["source_id"],
                    source_name=src["source_name"],
                    source_group=src["source_group"],
                    rss_url=src["rss_url"],
                    reliability_weight=src["reliability_weight"],
                    enabled=src.get("enabled", True),
                )
            )
    await db.commit()


async def fetch_feed(source: dict) -> list[dict]:
    parsed = await asyncio.to_thread(feedparser.parse, source["rss_url"])
    items = []
    for entry in parsed.entries:
        items.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "summary": entry.get("summary", ""),
            }
        )
    return items


def payload_hash_for_item(item: dict) -> str:
    payload_str = json.dumps(item, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


async def fetch_existing_payload_hashes(db: AsyncSession, hashes: list[str]) -> set[str]:
    """Return payload_hash values already in raw_items (scalar-only, no ORM load)."""
    existing: set[str] = set()
    if not hashes:
        return existing
    for offset in range(0, len(hashes), HASH_CHUNK_SIZE):
        chunk = hashes[offset : offset + HASH_CHUNK_SIZE]
        stmt = select(RawItem.payload_hash).where(RawItem.payload_hash.in_(chunk))
        result = await db.execute(stmt)
        existing.update(row[0] for row in result.all())
    return existing


def _build_row_dict(src: dict, item: dict, payload_hash: str, fetched_at: datetime) -> dict:
    return {
        "id": uuid.uuid4(),
        "fetched_at": fetched_at,
        "source_system": src["source_id"],
        "source_endpoint": src["rss_url"],
        "source_id": src["source_id"],
        "source_group": src["source_group"],
        "reliability_weight": src["reliability_weight"],
        "payload_json": item,
        "payload_hash": payload_hash,
    }


async def insert_raw_items_ignore_duplicates(db: AsyncSession, rows: list[dict]) -> int:
    """Bulk insert new rows; skip duplicates via UNIQUE(payload_hash) + ON CONFLICT DO NOTHING."""
    if not rows:
        return 0
    inserted = 0
    for offset in range(0, len(rows), HASH_CHUNK_SIZE):
        chunk = rows[offset : offset + HASH_CHUNK_SIZE]
        stmt = insert(RawItem.__table__).values(chunk)
        stmt = stmt.on_conflict_do_nothing(index_elements=["payload_hash"])
        result = await db.execute(stmt)
        if result.rowcount is not None and result.rowcount >= 0:
            inserted += result.rowcount
    return inserted


async def ingest_feed_for_source(db: AsyncSession, src: dict, items: list[dict]) -> int:
    """Process one RSS source: batch dedupe check, insert only new hashes."""
    if not items:
        return 0

    fetched_at = datetime.now(timezone.utc)
    pending: list[tuple[str, dict]] = []
    seen_in_feed: set[str] = set()

    for item in items:
        phash = payload_hash_for_item(item)
        if phash in seen_in_feed:
            continue
        seen_in_feed.add(phash)
        pending.append((phash, item))

    if not pending:
        return 0

    all_hashes = [h for h, _ in pending]
    existing = await fetch_existing_payload_hashes(db, all_hashes)
    new_rows = [
        _build_row_dict(src, item, phash, fetched_at)
        for phash, item in pending
        if phash not in existing
    ]

    if not new_rows:
        return 0

    return await insert_raw_items_ignore_duplicates(db, new_rows)


async def run_ingest(db: AsyncSession):
    logger.info("Starting ingest job (batch dedupe, chunk=%s)", HASH_CHUNK_SIZE)

    yaml_sources = load_sources_from_yaml()
    if not yaml_sources:
        logger.error("No sources found. Aborting ingest.")
        return

    await sync_sources_to_db(db, yaml_sources)

    total_new = 0
    for src in yaml_sources:
        source_id = src["source_id"]
        try:
            items = await fetch_feed(src)
            logger.info("Fetched %s items from %s", len(items), source_id)

            new_count = await ingest_feed_for_source(db, src, items)
            await db.commit()
            db.expire_all()

            total_new += new_count
            group = src.get("source_group") or ""
            logger.info(
                "Inserted %s new items for %s (fetched=%s, source_group=%s)",
                new_count,
                source_id,
                len(items),
                group,
            )

        except Exception as e:
            logger.error("Error fetching from %s: %s", source_id, e)
            await db.rollback()
            continue

    logger.info("Finished ingest job (total new rows=%s)", total_new)


if __name__ == "__main__":
    async def main():
        async with AsyncSessionLocal() as session:
            await run_ingest(session)

    asyncio.run(main())
