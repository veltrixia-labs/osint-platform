"""
Backfill CRYPTO topic alignment for Items and AlertLogs (last N days).

Fixes legacy rows where source_group=crypto but category/topic was classified as MARKET.

Usage (repo root, DATABASE_URL or .env):
  py -3 scripts/backfill_crypto_categories.py --dry-run
  py -3 scripts/backfill_crypto_categories.py --days 7
  py -3 scripts/backfill_crypto_categories.py --days 7 --regenerate-free-alerts --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, or_, select
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog, Item, TrendSignal
from processor.lightweight_topic import infer_topic_from_text
from processor.topic_registry import normalize_canonical_topic

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_crypto")

CRYPTO_INTERNAL = "crypto_geopolitics"
CRYPTO_STRATEGIC = "CRYPTO"
CRYPTO_SOURCE_GROUP = "crypto"

CRYPTO_SOURCE_IDS = frozenset({
    "coindesk_rss",
    "cointelegraph_rss",
    "cryptoslate_feed",
})

MARKET_TOPIC_VALUES = frozenset({
    "MARKET",
    "GLOBAL_MARKET_INTELLIGENCE",
    "GEOPOLITICS",
    "global_market_intelligence",
    "market_sentiment",
    "geopolitics",
    "global",
})


def _item_needs_crypto_category(item: Item) -> bool:
    sg = (item.source_group or "").strip().lower()
    sid = (item.source_id or "").strip().lower()
    if sg == CRYPTO_SOURCE_GROUP or sid in CRYPTO_SOURCE_IDS:
        return (item.category or "") != CRYPTO_INTERNAL or (item.rough_category or "") != CRYPTO_INTERNAL
    return False


def _infer_item_category(item: Item) -> str:
    text = f"{item.title or ''} {item.summary or ''}"
    return infer_topic_from_text(
        text,
        raw_topic=item.category,
        source_group=item.source_group,
    )


def _alert_should_be_crypto(alert: AlertLog, crypto_item_ids: set[str]) -> bool:
    topic = (alert.topic or "").strip()
    canonical = normalize_canonical_topic(topic)
    if canonical == CRYPTO_STRATEGIC:
        return False
    if canonical in ("ENERGY", "DEFENSE", "AI_TECH", "SUPPLY_CHAIN"):
        return False

    meta = alert.metadata_json if isinstance(alert.metadata_json, dict) else {}

    related = [str(r) for r in (meta.get("related_item_ids") or [])]
    if related:
        crypto_hits = sum(1 for rid in related if rid in crypto_item_ids)
        if crypto_hits and crypto_hits >= max(1, len(related) // 2):
            return True

    evidence = meta.get("evidence_list") or []
    crypto_domains = ("coindesk", "cointelegraph", "cryptoslate", "decrypt.co")
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        blob = f"{ev.get('domain', '')} {ev.get('url', '')} {ev.get('title', '')}".lower()
        if any(d in blob for d in crypto_domains):
            return True

    internal = (meta.get("internal_topic") or "").strip()
    if internal == CRYPTO_INTERNAL and (topic in MARKET_TOPIC_VALUES or canonical == "MARKET"):
        return True

    if topic in MARKET_TOPIC_VALUES or canonical == "MARKET":
        label = f"{alert.target_label or ''} {meta.get('description', '')}".lower()
        if any(
            kw in label
            for kw in (
                "bitcoin",
                "crypto",
                "ethereum",
                "stablecoin",
                "blockchain",
                "defi",
                "binance",
                "coinbase",
            )
        ):
            return True

    return False


async def backfill_items(db, *, cutoff: datetime, dry_run: bool) -> dict:
    stmt = (
        select(Item)
        .where(Item.created_at >= cutoff)
        .where(
            or_(
                func.lower(Item.source_group) == CRYPTO_SOURCE_GROUP,
                Item.source_id.in_(list(CRYPTO_SOURCE_IDS)),
            )
        )
    )
    items = (await db.execute(stmt)).scalars().all()
    to_update: list[Item] = []
    for item in items:
        if _item_needs_crypto_category(item):
            to_update.append(item)
        else:
            inferred = _infer_item_category(item)
            if inferred == CRYPTO_INTERNAL and (
                item.category != CRYPTO_INTERNAL or item.rough_category != CRYPTO_INTERNAL
            ):
                to_update.append(item)

    logger.info(
        "Items (crypto source, last %s days): scanned=%s to_update=%s",
        (datetime.now(timezone.utc) - cutoff).days,
        len(items),
        len(to_update),
    )

    if dry_run:
        for item in to_update[:10]:
            logger.info(
                "  [dry-run] item %s | %s | category %r -> %s",
                item.id,
                item.source_id,
                item.category,
                CRYPTO_INTERNAL,
            )
        if len(to_update) > 10:
            logger.info("  ... and %s more", len(to_update) - 10)
        return {"items_scanned": len(items), "items_updated": len(to_update)}

    updated = 0
    for item in to_update:
        item.category = CRYPTO_INTERNAL
        item.rough_category = CRYPTO_INTERNAL
        db.add(item)
        updated += 1
    if updated:
        await db.commit()
    return {"items_scanned": len(items), "items_updated": updated}


async def normalize_crypto_alert_topics(db, *, cutoff: datetime, dry_run: bool) -> dict:
    """Unify legacy AlertLog.topic=crypto_geopolitics -> strategic CRYPTO."""
    stmt = (
        select(AlertLog)
        .where(AlertLog.triggered_at >= cutoff)
        .where(AlertLog.topic == CRYPTO_INTERNAL)
    )
    rows = (await db.execute(stmt)).scalars().all()
    logger.info("AlertLogs with legacy topic %s: %s to normalize", CRYPTO_INTERNAL, len(rows))
    if dry_run:
        return {"legacy_crypto_alerts": len(rows), "legacy_normalized": len(rows)}

    for alert in rows:
        alert.topic = CRYPTO_STRATEGIC
        meta = dict(alert.metadata_json) if isinstance(alert.metadata_json, dict) else {}
        meta["internal_topic"] = CRYPTO_INTERNAL
        fa = meta.get("free_alert")
        if isinstance(fa, dict):
            fa = dict(fa)
            fa["topic"] = CRYPTO_STRATEGIC
            meta["free_alert"] = fa
        alert.metadata_json = meta
        flag_modified(alert, "metadata_json")
        db.add(alert)
    if rows:
        await db.commit()
    return {"legacy_crypto_alerts": len(rows), "legacy_normalized": len(rows)}


async def backfill_alert_logs(
    db,
    *,
    cutoff: datetime,
    crypto_item_ids: set[str],
    dry_run: bool,
) -> dict:
    stmt = select(AlertLog).where(AlertLog.triggered_at >= cutoff)
    alerts = (await db.execute(stmt)).scalars().all()
    to_fix: list[AlertLog] = []
    for alert in alerts:
        if _alert_should_be_crypto(alert, crypto_item_ids):
            to_fix.append(alert)

    logger.info(
        "AlertLogs (last window): scanned=%s to_retopic=%s",
        len(alerts),
        len(to_fix),
    )

    if dry_run:
        for alert in to_fix[:10]:
            logger.info(
                "  [dry-run] alert %s | topic %r -> %s",
                alert.id,
                alert.topic,
                CRYPTO_STRATEGIC,
            )
        return {"alerts_scanned": len(alerts), "alerts_updated": len(to_fix)}

    updated = 0
    for alert in to_fix:
        alert.topic = CRYPTO_STRATEGIC
        meta = dict(alert.metadata_json) if isinstance(alert.metadata_json, dict) else {}
        meta["internal_topic"] = CRYPTO_INTERNAL
        fa = meta.get("free_alert")
        if isinstance(fa, dict):
            fa = dict(fa)
            fa["topic"] = CRYPTO_STRATEGIC
            meta["free_alert"] = fa
        alert.metadata_json = meta
        flag_modified(alert, "metadata_json")
        db.add(alert)
        updated += 1
    if updated:
        await db.commit()
    return {"alerts_scanned": len(alerts), "alerts_updated": updated}


async def backfill_trend_signals(db, *, cutoff: datetime, dry_run: bool) -> dict:
    """Align TrendSignal.topic when still on internal market codes but text is crypto."""
    stmt = select(TrendSignal).where(TrendSignal.created_at >= cutoff)
    signals = (await db.execute(stmt)).scalars().all()
    to_fix = []
    for sig in signals:
        inferred = infer_topic_from_text(
            f"{sig.target_label or ''} {sig.description or ''}",
            raw_topic=sig.topic,
        )
        if inferred == CRYPTO_INTERNAL and (sig.topic or "") != CRYPTO_INTERNAL:
            to_fix.append(sig)

    logger.info("TrendSignals: scanned=%s to_update=%s", len(signals), len(to_fix))
    if dry_run:
        return {"signals_scanned": len(signals), "signals_updated": len(to_fix)}

    for sig in to_fix:
        sig.topic = CRYPTO_INTERNAL
        db.add(sig)
    if to_fix:
        await db.commit()
    return {"signals_scanned": len(signals), "signals_updated": len(to_fix)}


async def load_crypto_item_ids(db, cutoff: datetime) -> set[str]:
    stmt = (
        select(Item.id)
        .where(Item.created_at >= cutoff)
        .where(
            or_(
                func.lower(Item.source_group) == CRYPTO_SOURCE_GROUP,
                Item.source_id.in_(list(CRYPTO_SOURCE_IDS)),
            )
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {str(r) for r in rows}


async def regenerate_free_alerts(db, *, cutoff: datetime, limit: int, dry_run: bool) -> int:
    from jobs.free_alert_feed_generator import persist_free_alert_feed_item

    stmt = (
        select(AlertLog)
        .where(AlertLog.triggered_at >= cutoff)
        .where(
            or_(
                AlertLog.topic == CRYPTO_STRATEGIC,
                AlertLog.topic == CRYPTO_INTERNAL,
            )
        )
        .order_by(AlertLog.triggered_at.desc())
        .limit(limit * 2)
    )
    rows = (await db.execute(stmt)).scalars().all()
    ok = 0
    for alert in rows:
        if ok >= limit:
            break
        if dry_run:
            ok += 1
            continue
        try:
            await persist_free_alert_feed_item(db, alert, commit=True)
            ok += 1
        except Exception as e:
            logger.exception("free_alert regenerate failed for %s: %s", alert.id, e)
            await db.rollback()
    logger.info("Regenerated free_alert payloads: %s", ok)
    return ok


async def print_summary(db, cutoff: datetime) -> None:
    item_crypto = (
        await db.execute(
            select(func.count())
            .select_from(Item)
            .where(Item.created_at >= cutoff)
            .where(func.lower(Item.source_group) == CRYPTO_SOURCE_GROUP)
            .where(Item.category == CRYPTO_INTERNAL)
        )
    ).scalar_one()
    item_crypto_total = (
        await db.execute(
            select(func.count())
            .select_from(Item)
            .where(Item.created_at >= cutoff)
            .where(func.lower(Item.source_group) == CRYPTO_SOURCE_GROUP)
        )
    ).scalar_one()
    alert_crypto = (
        await db.execute(
            select(func.count())
            .select_from(AlertLog)
            .where(AlertLog.triggered_at >= cutoff)
            .where(
                or_(
                    AlertLog.topic == CRYPTO_STRATEGIC,
                    AlertLog.topic == CRYPTO_INTERNAL,
                )
            )
        )
    ).scalar_one()
    logger.info(
        "Post-backfill: crypto items %s/%s with category=%s; alerts with CRYPTO topic=%s",
        item_crypto,
        item_crypto_total,
        CRYPTO_INTERNAL,
        alert_crypto,
    )


async def main() -> None:
    p = argparse.ArgumentParser(description="Backfill CRYPTO categories and alert topics")
    p.add_argument("--days", type=int, default=7, help="Lookback window (default 7)")
    p.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    p.add_argument(
        "--regenerate-free-alerts",
        action="store_true",
        help="Re-run persist_free_alert_feed_item for CRYPTO AlertLogs",
    )
    p.add_argument("--limit", type=int, default=50, help="Max free_alert regenerations")
    args = p.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    logger.info("Backfill window: created/triggered >= %s (dry_run=%s)", cutoff.isoformat(), args.dry_run)

    async with AsyncSessionLocal() as db:
        item_stats = await backfill_items(db, cutoff=cutoff, dry_run=args.dry_run)
        legacy_stats = await normalize_crypto_alert_topics(db, cutoff=cutoff, dry_run=args.dry_run)
        crypto_ids = await load_crypto_item_ids(db, cutoff)
        alert_stats = await backfill_alert_logs(
            db, cutoff=cutoff, crypto_item_ids=crypto_ids, dry_run=args.dry_run
        )
        signal_stats = await backfill_trend_signals(db, cutoff=cutoff, dry_run=args.dry_run)

        if args.regenerate_free_alerts and not args.dry_run:
            await regenerate_free_alerts(db, cutoff=cutoff, limit=args.limit, dry_run=False)
        elif args.regenerate_free_alerts:
            logger.info("[dry-run] Would regenerate up to %s free_alert payloads", args.limit)

        if not args.dry_run:
            await print_summary(db, cutoff)

    logger.info(
        "Done. items=%s legacy=%s alerts=%s signals=%s",
        item_stats,
        legacy_stats,
        alert_stats,
        signal_stats,
    )


if __name__ == "__main__":
    asyncio.run(main())
