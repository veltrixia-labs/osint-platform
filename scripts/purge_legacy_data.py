"""
HARD RESET of legacy processed intelligence — DESTRUCTIVE, BATCHED.

Wipes the alert/cluster layer so the new 0.40-threshold ingestion engine can
repopulate cleanly. Targets ONLY processed clusters + alerts + their delivery
bridge:
    - alert_deliveries   (alert -> analyst delivery/evidence bridge)
    - alert_logs         (alerts)
    - event_clusters     (clusters)  [items.cluster_id is nulled first]

PRESERVES everything else: analyst_profiles (users), raw_items / items (raw feed),
reports, all external_* / market_data_* / bea_* / cot_* data feeds,
stakeholders/dependencies, the spatial engine, and the ARCHIVAL
monthly_trend_reports. trend_signals is intentionally NOT purged.

WHY BATCHED: a single-transaction bulk delete of ~47k rows hung on lock contention
with the live ingestion writer. This version deletes in small chunks, COMMITTING
and sleeping between batches so the live pipeline can interleave its own locks.
Each batch is appended to a JSONL backup BEFORE deletion, so the wipe is
recoverable and resumable (the drain loop naturally continues where it left off).

Usage (repo root, DATABASE_URL / .env):
  py -3 -u scripts/purge_legacy_data.py                      # DRY-RUN: counts only
  py -3 -u scripts/purge_legacy_data.py --execute            # batched live purge
  py -3 -u scripts/purge_legacy_data.py --execute --batch-size 2000 --pause 0.3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, delete, update, func

from db.database import AsyncSessionLocal
from db.models import AlertDelivery, AlertLog, EventCluster, Item, TrendSignal

# Deleted in FK-safe order: bridge -> alerts -> (null item links) -> clusters.
PURGE_MODELS = [AlertDelivery, AlertLog, EventCluster]


async def _count(s, model) -> int:
    return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def _drain_delete(s, model, backup_fh, batch: int, pause: float) -> int:
    """Delete `model` rows in committed chunks of `batch`, backing each chunk up
    to `backup_fh` (JSONL) first, sleeping `pause`s between commits."""
    total = 0
    while True:
        ids = (await s.execute(select(model.id).limit(batch))).scalars().all()
        if not ids:
            break
        rows = (await s.execute(
            select(model.__table__).where(model.__table__.c.id.in_(ids))
        )).mappings().all()
        for r in rows:
            backup_fh.write(json.dumps({"_table": model.__tablename__, **dict(r)},
                                       default=str, ensure_ascii=False) + "\n")
        await s.execute(delete(model).where(model.id.in_(ids)))
        await s.commit()
        total += len(ids)
        print(f"  {model.__tablename__:<18} deleted {total:>8,} ...", flush=True)
        await asyncio.sleep(pause)
    return total


async def _drain_null_items(s, batch: int, pause: float) -> int:
    """Null items.cluster_id in committed chunks (breaks the FK to event_clusters
    without deleting the raw feed rows)."""
    total = 0
    while True:
        ids = (await s.execute(
            select(Item.id).where(Item.cluster_id.isnot(None)).limit(batch)
        )).scalars().all()
        if not ids:
            break
        await s.execute(update(Item).where(Item.id.in_(ids)).values(cluster_id=None))
        await s.commit()
        total += len(ids)
        print(f"  items.cluster_id  nulled  {total:>8,} ...", flush=True)
        await asyncio.sleep(pause)
    return total


async def main() -> None:
    p = argparse.ArgumentParser(description="Batched hard reset of legacy alerts + clusters")
    p.add_argument("--execute", action="store_true", help="Perform the wipe (default: dry-run)")
    p.add_argument("--batch-size", type=int, default=2000, help="Rows per commit (default 2000)")
    p.add_argument("--pause", type=float, default=0.3, help="Seconds between commits (default 0.3)")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        counts = {m.__tablename__: await _count(s, m) for m in PURGE_MODELS}
        items_linked = (await s.execute(
            select(func.count()).select_from(Item).where(Item.cluster_id.isnot(None))
        )).scalar_one()
        trend_n = await _count(s, TrendSignal)

        print("=" * 72, flush=True)
        print("BATCHED LEGACY PURGE  —", "EXECUTE (LIVE)" if args.execute else "DRY-RUN", flush=True)
        print("=" * 72, flush=True)
        for t, n in counts.items():
            print(f"  WILL DELETE {t:<18} {n:>9,} rows", flush=True)
        print(f"  WILL NULL   items.cluster_id {items_linked:>9,} (raw rows KEPT)", flush=True)
        print(f"  NOT TOUCHED trend_signals    {trend_n:>9,} (out of scope)", flush=True)
        if args.execute:
            print(f"  batch_size={args.batch_size}  pause={args.pause}s", flush=True)

        if not args.execute:
            print("\nDRY-RUN complete: no rows deleted.", flush=True)
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"legacy_purge_batched_{stamp}.jsonl")
        print(f"\nStreaming backup -> {backup_path}\n", flush=True)

        deleted = {}
        with open(backup_path, "w", encoding="utf-8") as fh:
            deleted["alert_deliveries"] = await _drain_delete(s, AlertDelivery, fh, args.batch_size, args.pause)
            deleted["alert_logs"] = await _drain_delete(s, AlertLog, fh, args.batch_size, args.pause)
            nulled = await _drain_null_items(s, args.batch_size, args.pause)
            deleted["event_clusters"] = await _drain_delete(s, EventCluster, fh, args.batch_size, args.pause)

        after = {m.__tablename__: await _count(s, m) for m in PURGE_MODELS}
        residual_items = (await s.execute(
            select(func.count()).select_from(Item).where(Item.cluster_id.isnot(None))
        )).scalar_one()
        print("\n" + "-" * 72, flush=True)
        print(f"DELETED: {deleted}  (items nulled: {nulled:,})", flush=True)
        print("POST-PURGE counts (residual = live pipeline writes since start):", flush=True)
        for t, n in after.items():
            print(f"  {t:<18} {n:>9,} rows", flush=True)
        print(f"  items w/ cluster_id {residual_items:>9,}", flush=True)
        print("RESULT: legacy payload cleared (residuals are fresh post-purge ingestion).", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
