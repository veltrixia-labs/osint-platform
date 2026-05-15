"""
Backfill AlertLog.location_lat / location_lng using LocationResolver for rows
where location_lat was never set.

Usage (from repo root):
  .venv\\Scripts\\python.exe scratch/backfill_locations.py
  .venv\\Scripts\\python.exe scratch/backfill_locations.py --dry-run
  .venv\\Scripts\\python.exe scratch/backfill_locations.py --stats-only
  .venv\\Scripts\\python.exe scratch/backfill_locations.py --backfill-location-meta
  .venv\\Scripts\\python.exe scratch/backfill_locations.py --test-api
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from processor.location_resolver import LocationResolver


def _alert_text_for_resolution(alert: AlertLog) -> str:
    """Combine target_label with metadata (description, free_alert, evidence titles)."""
    parts: list[str] = []
    if alert.target_label:
        parts.append(str(alert.target_label))
    meta = alert.metadata_json or {}
    if isinstance(meta, dict):
        desc = meta.get("description")
        if desc:
            parts.append(str(desc))
        fa = meta.get("free_alert")
        if isinstance(fa, dict):
            for key in ("title", "summary_md", "body_md"):
                v = fa.get(key)
                if v:
                    parts.append(str(v)[:4000])
        for ev in meta.get("evidence_list") or []:
            if isinstance(ev, dict):
                t = ev.get("title") or ev.get("headline")
                if t:
                    parts.append(str(t))
    return " ".join(parts).strip()


async def print_stats(db: AsyncSession) -> None:
    total = (await db.execute(select(func.count()).select_from(AlertLog))).scalar() or 0
    with_coords = (
        await db.execute(
            select(func.count())
            .select_from(AlertLog)
            .where(AlertLog.location_lat.isnot(None), AlertLog.location_lng.isnot(None))
        )
    ).scalar() or 0
    lat_null = (
        await db.execute(
            select(func.count()).select_from(AlertLog).where(AlertLog.location_lat.is_(None))
        )
    ).scalar() or 0
    print("--- AlertLog location stats ---")
    print(f"total rows:              {total}")
    print(f"lat & lng both NOT NULL: {with_coords}")
    print(f"location_lat IS NULL:    {lat_null}")


async def run_backfill(dry_run: bool) -> int:
    resolver = LocationResolver()
    updated = 0
    examined = 0
    async with AsyncSessionLocal() as db:
        await print_stats(db)
        stmt = (
            select(AlertLog)
            .where(AlertLog.location_lat.is_(None))
            .order_by(AlertLog.triggered_at.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        print(f"\nCandidates (location_lat IS NULL): {len(rows)}")
        for alert in rows:
            examined += 1
            text = _alert_text_for_resolution(alert)
            if not text:
                continue
            detail = resolver.resolve_heuristically_detailed(text)
            if not detail:
                continue
            updated += 1
            print(
                f"  match id={alert.id} entity={detail.entity_id!r} "
                f"type={detail.match_type} conf={detail.confidence} "
                f"lat={detail.lat:.4f} lng={detail.lng:.4f}"
            )
            if dry_run:
                continue
            alert.location_lat = detail.lat
            alert.location_lng = detail.lng
            meta = dict(alert.metadata_json) if isinstance(alert.metadata_json, dict) else {}
            meta["location_entity_id"] = detail.entity_id
            meta["location_resolution"] = {
                "entity_id": detail.entity_id,
                "display_name": detail.display_name,
                "confidence": detail.confidence,
                "match_type": detail.match_type,
                "matched_text": detail.matched_text,
            }
            alert.metadata_json = meta
            flag_modified(alert, "metadata_json")
        if not dry_run and updated:
            await db.commit()
        elif not dry_run:
            await db.rollback()
    print(
        f"\n{'Would update' if dry_run else 'Updated'} rows with new coordinates: "
        f"{updated} (examined {examined})"
    )
    return updated


async def run_backfill_location_meta_only(dry_run: bool) -> int:
    """Set location_entity_id / location_resolution on rows missing them (coords optional)."""
    resolver = LocationResolver()
    updated = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AlertLog).order_by(AlertLog.triggered_at.desc()))).scalars().all()
        print(f"\nScanning {len(rows)} alerts for missing location_entity_id...")
        for alert in rows:
            meta = alert.metadata_json or {}
            if isinstance(meta, dict) and meta.get("location_entity_id"):
                continue
            text = _alert_text_for_resolution(alert)
            if not text:
                continue
            detail = resolver.resolve_heuristically_detailed(text)
            if not detail:
                continue
            updated += 1
            print(f"  meta id={alert.id} entity={detail.entity_id!r}")
            if dry_run:
                continue
            meta2 = dict(meta) if isinstance(meta, dict) else {}
            meta2["location_entity_id"] = detail.entity_id
            meta2["location_resolution"] = {
                "entity_id": detail.entity_id,
                "display_name": detail.display_name,
                "confidence": detail.confidence,
                "match_type": detail.match_type,
                "matched_text": detail.matched_text,
            }
            alert.metadata_json = meta2
            flag_modified(alert, "metadata_json")
        if not dry_run and updated:
            await db.commit()
        elif not dry_run:
            await db.rollback()
    print(f"\n{'Would update' if dry_run else 'Updated'} metadata rows: {updated}")
    return updated


def test_map_signals_api_sync() -> None:
    """Simulate GET /api/pro/map/signals with async tier override (no JWT)."""
    from fastapi.testclient import TestClient

    from api.main import app
    from api.routes import pro_reports

    async def fake_tier() -> str:
        return "pro"

    app.dependency_overrides[pro_reports.get_current_tier] = fake_tier
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            r = client.get("/api/pro/map/signals?limit=20")
            print("\n--- GET /api/pro/map/signals (TestClient, tier=pro) ---")
            print("status:", r.status_code)
            data = r.json()
            assert isinstance(data, dict)
            print("top-level keys:", sorted(data.keys()))
            sigs = data.get("signals")
            assert isinstance(sigs, list)
            print("signals returned:", len(sigs), "count field:", data.get("count"))
            if sigs:
                s0 = sigs[0]
                print("first signal keys:", sorted(s0.keys()))
                print("first lat/lng:", s0.get("lat"), s0.get("lng"))
    finally:
        app.dependency_overrides.pop(pro_reports.get_current_tier, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Resolve only; do not commit")
    parser.add_argument("--stats-only", action="store_true")
    parser.add_argument(
        "--backfill-location-meta",
        action="store_true",
        help="Fill location_entity_id / location_resolution on alerts missing them",
    )
    args = parser.parse_args()

    if args.stats_only:

        async def _stats() -> None:
            async with AsyncSessionLocal() as db:
                await print_stats(db)

        asyncio.run(_stats())
    elif args.backfill_location_meta:
        asyncio.run(run_backfill_location_meta_only(dry_run=args.dry_run))
    else:
        asyncio.run(run_backfill(dry_run=args.dry_run))

    if args.test_api:
        test_map_signals_api_sync()


if __name__ == "__main__":
    main()
