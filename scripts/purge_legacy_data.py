"""
HARD RESET of legacy processed intelligence — DESTRUCTIVE.

Wipes the alert/cluster layer so the new 0.40-threshold ingestion engine can
repopulate from scratch. Targets ONLY processed clusters + alerts + their
delivery bridge:
    - alert_deliveries   (alert -> analyst delivery/evidence bridge)
    - alert_logs         (alerts)
    - event_clusters     (clusters)

PRESERVES everything else: analyst_profiles (users), raw_items / items (raw feed
— items.cluster_id is set NULL so rows survive), reports, all external_* /
market_data_* / bea_* / cot_* data feeds, stakeholders/dependencies, the spatial
engine, and the ARCHIVAL monthly_trend_reports (which must never be purged).

trend_signals is intentionally NOT purged (not in the requested scope). Stale
signals in the last ~30h may regenerate sparse alerts via the new hardened
binding; pass nothing here removes them — purge separately if a fuller reset is
wanted.

Before deleting, --execute first writes a full JSON backup of the purged rows to
backups/legacy_purge_<UTC>.json so the wipe is recoverable.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/purge_legacy_data.py              # DRY-RUN: counts only, no writes
  py -3 scripts/purge_legacy_data.py --execute    # back up, then permanently DELETE
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

# Wiped in FK-safe order: bridge first, then alerts, then clusters.
PURGE_MODELS = [AlertDelivery, AlertLog, EventCluster]

PRESERVED = [
    "analyst_profiles (user accounts)",
    "raw_items / items (raw source feeds — items.cluster_id nulled, rows kept)",
    "reports / article_outputs (separate product surface)",
    "monthly_trend_reports (ARCHIVAL — must never be purged)",
    "spatial_nodes / spatial_edges / contagion_history (self-refreshing engine)",
    "external_* / market_data_* / bea_* / cot_* (raw external data feeds)",
    "stakeholders / dependencies / predictions (entity backbone)",
    "source_registry / topics / system configs",
]


async def _count(s, model) -> int:
    return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def main() -> None:
    p = argparse.ArgumentParser(description="Hard reset of legacy alerts + clusters")
    p.add_argument("--execute", action="store_true", help="Perform the wipe (default: dry-run)")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        counts = {m.__tablename__: await _count(s, m) for m in PURGE_MODELS}
        items_linked = (await s.execute(
            select(func.count()).select_from(Item).where(Item.cluster_id.isnot(None))
        )).scalar_one()
        trend_n = await _count(s, TrendSignal)

        print("=" * 72)
        print("LEGACY DATA PURGE  —", "EXECUTE (LIVE)" if args.execute else "DRY-RUN (no writes)")
        print("=" * 72)
        print("WILL DELETE:")
        for t, n in counts.items():
            print(f"  {t:<18} {n:>9,} rows")
        print(f"WILL NULL : items.cluster_id on {items_linked:,} raw item(s) (rows KEPT)")
        print(f"NOT TOUCHED: trend_signals = {trend_n:,} rows (outside requested scope)")
        print("PRESERVED:")
        for t in PRESERVED:
            print(f"  - {t}")

        if not args.execute:
            print("\nDRY-RUN complete: NO rows deleted. Re-run with --execute to apply.")
            return

        # 1) Safety backup of every row we are about to delete.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"legacy_purge_{stamp}.json")
        dump: dict = {}
        for m in PURGE_MODELS:
            rows = (await s.execute(select(m.__table__))).mappings().all()
            dump[m.__tablename__] = [dict(r) for r in rows]
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(dump, f, default=str, ensure_ascii=False)
        print(f"\nBackup written: {backup_path}  ({sum(len(v) for v in dump.values()):,} rows)")

        # 2) Delete in FK-safe order (bridge -> null item links -> alerts -> clusters).
        await s.execute(delete(AlertDelivery))
        await s.execute(update(Item).where(Item.cluster_id.isnot(None)).values(cluster_id=None))
        await s.execute(delete(AlertLog))
        await s.execute(delete(EventCluster))
        await s.commit()

        # 3) Verify the clean slate.
        after = {m.__tablename__: await _count(s, m) for m in PURGE_MODELS}
        print("POST-PURGE counts (expect 0):")
        for t, n in after.items():
            print(f"  {t:<18} {n:>9,} rows")
        print("RESULT:", "CLEAN SLATE ✓" if all(v == 0 for v in after.values())
              else "WARNING — residual rows remain")


if __name__ == "__main__":
    asyncio.run(main())
