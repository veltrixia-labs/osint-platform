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
from processor.classify import llm_classify_fallback  # (C-1) keyword-miss rescue
from processor.classify import detect_ja, llm_translate_to_en  # (C-4) JA translate-at-ingest
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

    metrics = {"normalized": 0, "noise_filtered": 0, "deduped": 0, "unclassified": 0}
    candidates: list[dict] = []
    pending_llm: list[dict] = []  # (C-1) keyword-miss, awaiting LLM rescue
    _enable_llm_topic = os.getenv("ENABLE_LLM_TOPIC", "false").lower() == "true"

    # (C-4) JA translate-at-ingest pre-pass (flag-gated). When ON, JA raw items
    # are batch-translated to English BEFORE the length gate / title_hash, so the
    # whole English pipeline downstream runs unchanged on a real English title.
    # When OFF, `translations` stays empty -> every branch below is byte-identical.
    _enable_translate = os.getenv("ENABLE_LLM_TRANSLATE", "false").lower() == "true"
    translations: dict = {}  # {str(raw.id): {"title_en", "title_original", "lang"}}
    if _enable_translate:
        ja_cands = []
        for raw in raw_items:
            _p = raw.payload_json or {}
            _t = sanitize_unicode_text(_p.get("title", "") or "")
            if _t and detect_ja(_t, _p.get("language")):
                ja_cands.append({
                    "id": str(raw.id),
                    "title": _t,
                    "summary": sanitize_unicode_text(_p.get("summary", "") or ""),
                })
        if ja_cands:
            try:
                _verdicts = await llm_translate_to_en(ja_cands)
            except Exception as _tx_exc:  # double-guard; fn already isolates
                logger.warning("[LLM_TRANSLATE] pre-pass errored (non-fatal): %s", _tx_exc)
                _verdicts = {}
            for _c in ja_cands:
                _te = _verdicts.get(_c["id"])
                if _te:
                    translations[_c["id"]] = {
                        "title_en": _te,
                        "title_original": _c["title"],
                        "lang": "ja",
                    }

    for raw in raw_items:
        payload = raw.payload_json or {}
        url = payload.get("link", "")
        title = sanitize_unicode_text(payload.get("title", "") or "")
        summary = sanitize_unicode_text(payload.get("summary", "") or "")

        # (C-4) If this JA item was translated, swap in the English title for all
        # downstream processing (length gate, title_hash, keyword/LLM topic,
        # clustering) and remember the original + language for persistence.
        _tr = translations.get(str(raw.id))
        if _tr:
            title_original = _tr["title_original"]
            lang = "ja"
            title = _tr["title_en"]
            summary = ""  # GDELT/translated path is title-only
            is_translated = True
        else:
            title_original = None
            lang = "en"
            is_translated = False

        if not url or not title:
            continue
        # Length gate: English RSS unchanged. Translated/title-only (GDELT) items
        # are admitted on title alone (no summary requirement); the minimum-signal
        # keyword rule still runs on the title downstream.
        _summary_ok = (len(summary) >= 20) or is_translated
        if len(title) < 15 or not _summary_ok:
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

        # Ingestion gate (strict): drops non-strategic media/entertainment noise
        # and unclassifiable general news (returns None) instead of force-fitting a
        # strategic domain. `title` enables the minimum-signal rule.
        topic_code = infer_topic_from_text(
            f"{title} {summary}",
            title=title,
            source_group=raw.source_group,
            strict=True,
        )
        if topic_code is None:
            # (C-1) Flag OFF -> identical to before: count + drop.
            # Flag ON -> stash for a single post-loop LLM batch; only items the
            # LLM maps to a real strategic domain are rescued, the rest still drop.
            if _enable_llm_topic:
                pending_llm.append(
                    {
                        "raw": raw,
                        "title_original": title_original,
                        "lang": lang,
                        "url_hash": url_hash,
                        "title_hash": title_hash,
                        "title": title,
                        "summary": summary,
                        "url": url,
                        "pub_date": pub_date,
                    }
                )
            else:
                metrics["unclassified"] += 1
            continue

        candidates.append(
            {
                "raw": raw,
                "title_original": title_original,
                "lang": lang,
                "url_hash": url_hash,
                "title_hash": title_hash,
                "title": title,
                "summary": summary,
                "url": url,
                "pub_date": pub_date,
                "topic_code": topic_code,
            }
        )

    # (C-1) Post-loop LLM rescue of keyword-miss candidates (flag-gated). Any
    # failure is swallowed inside llm_classify_fallback -> these items simply
    # stay dropped, exactly as before the flag existed.
    if _enable_llm_topic and pending_llm:
        try:
            verdicts = await llm_classify_fallback(pending_llm)
        except Exception as _llm_exc:  # defensive; fn already isolates, double-guard
            logger.warning("[LLM_TOPIC] rescue batch errored (non-fatal): %s", _llm_exc)
            verdicts = {}
        for _pc in pending_llm:
            _key = normalize_text(_pc["title"])
            _rescued = verdicts.get(_key)
            if _rescued:
                _pc["topic_code"] = _rescued
                candidates.append(_pc)
            else:
                metrics["unclassified"] += 1

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
                "title_original": c.get("title_original"),
                "lang": c.get("lang", "en"),
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
