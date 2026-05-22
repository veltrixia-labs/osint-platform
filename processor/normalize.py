import hashlib
import logging
import os
import re
from datetime import datetime, timezone, timedelta

from dateutil import parser as dt_parser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Item, RawItem
from processor.lightweight_topic import infer_topic_from_text
from reports.text_encoding import sanitize_unicode_text

logger = logging.getLogger(__name__)

DEDUP_CHUNK_SIZE = int(os.getenv("NORMALIZE_DEDUP_CHUNK_SIZE", "500"))


def normalize_text(text: str) -> str:
    """Removes non-alphanumeric chars and lowercases."""
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()


async def fetch_existing_dedup_keys(db: AsyncSession, keys: list[str]) -> set[str]:
    """Return dedup_key values already in items (scalar-only)."""
    existing: set[str] = set()
    if not keys:
        return existing
    for offset in range(0, len(keys), DEDUP_CHUNK_SIZE):
        chunk = keys[offset : offset + DEDUP_CHUNK_SIZE]
        stmt = select(Item.dedup_key).where(Item.dedup_key.in_(chunk))
        result = await db.execute(stmt)
        existing.update(row[0] for row in result.all())
    return existing


async def insert_items_ignore_duplicates(db: AsyncSession, rows: list[dict]) -> int:
    if not rows:
        return 0
    inserted = 0
    for offset in range(0, len(rows), DEDUP_CHUNK_SIZE):
        chunk = rows[offset : offset + DEDUP_CHUNK_SIZE]
        stmt = pg_insert(Item.__table__).values(chunk)
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])
        result = await db.execute(stmt)
        if result.rowcount is not None and result.rowcount >= 0:
            inserted += result.rowcount
    return inserted


async def run_normalize(db: AsyncSession):
    """
    High-Efficiency Normalize Job migrated from jobs/normalize_job.py.
    Handles Stage 1 normalization: Noise filtering and URL/title-hash deduplication.
    """
    logger.info("Starting Processor Normalize Job (batch dedupe, chunk=%s)", DEDUP_CHUNK_SIZE)

    lookback = datetime.now(timezone.utc) - timedelta(hours=12)
    stmt = (
        select(RawItem)
        .where(RawItem.created_at > lookback)
        .order_by(RawItem.created_at.desc())
        .limit(500)
    )
    result = await db.execute(stmt)
    raw_items = result.scalars().all()

    metrics = {"normalized": 0, "noise_filtered": 0, "deduped": 0}
    candidates: list[dict] = []

    for raw in raw_items:
        payload = raw.payload_json or {}
        url = payload.get("link", "")
        title = sanitize_unicode_text(payload.get("title", "") or "")
        summary = sanitize_unicode_text(payload.get("summary", "") or "")

        if not url or not title:
            continue

        if len(title) < 15 or len(summary) < 20:
            metrics["noise_filtered"] += 1
            continue

        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        title_norm = normalize_text(title)
        title_hash = hashlib.sha256(title_norm.encode("utf-8")).hexdigest()

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

        topic_code = infer_topic_from_text(
            f"{title} {summary}",
            source_group=raw.source_group,
        )

        candidates.append(
            {
                "raw": raw,
                "url_hash": url_hash,
                "title_hash": title_hash,
                "title": title,
                "summary": summary,
                "url": url,
                "pub_date": pub_date,
                "topic_code": topic_code,
            }
        )

    if not candidates:
        logger.info("Processor Normalize finished. Metrics: %s", metrics)
        return

    all_keys: list[str] = []
    for c in candidates:
        all_keys.append(c["url_hash"])
        all_keys.append(c["title_hash"])
    existing_keys = await fetch_existing_dedup_keys(db, all_keys)

    new_rows: list[dict] = []
    seen_url: set[str] = set()
    seen_title: set[str] = set()

    for c in candidates:
        url_hash = c["url_hash"]
        title_hash = c["title_hash"]
        if url_hash in existing_keys or title_hash in existing_keys:
            metrics["deduped"] += 1
            continue
        if url_hash in seen_url or title_hash in seen_title:
            metrics["deduped"] += 1
            continue

        seen_url.add(url_hash)
        seen_title.add(title_hash)
        raw = c["raw"]
        new_rows.append(
            {
                "type": "article",
                "dedup_key": url_hash,
                "published_at": c["pub_date"],
                "title": c["title"],
                "summary": c["summary"],
                "source_name": raw.source_system,
                "source_url": c["url"],
                "source_id": raw.source_id,
                "source_group": raw.source_group,
                "reliability_weight": raw.reliability_weight,
                "category": c["topic_code"],
                "rough_category": c["topic_code"],
                "geo": {},
                "tags": {},
            }
        )

    if new_rows:
        metrics["normalized"] = await insert_items_ignore_duplicates(db, new_rows)

    await db.commit()
    db.expire_all()
    logger.info("Processor Normalize finished. Metrics: %s", metrics)
