"""
Direct in-place upgrade: for every pro_structural Report, rebuild its
spatial_contagion block from the persisted signal alert + cached macro
context and UPDATE the row's structured_payload.

This avoids the INSERT/dedup path entirely — we never create a new row,
we just rewrite the JSON of the existing one with the new v2 schema.
Safer and guaranteed-coverage for the regeneration mandate.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from db.database import AsyncSessionLocal
from db.models import Report, AlertLog
from analysis.pro_structural_context import (
    _compute_spatial_contagion,
    _compute_systemic_fragility,
)


async def main() -> int:
    upgraded = 0
    skipped = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Report).where(Report.report_type == "pro_structural")
        )).scalars().all()

        print(f"Found {len(rows)} pro_structural reports to upgrade in-place.")

        for r in rows:
            payload = dict(r.structured_payload or {})
            try:
                # Re-derive signal/related_events from what's already persisted
                # so we never need to re-fetch alerts (decouples from data drift).
                sig = payload.get("signal") or {}
                related_events = payload.get("event_timeline") or []
                synth_ctx = {
                    "signal": sig,
                    "related_events": related_events,
                    "event_timeline": related_events,
                }
                # Pull fragility metrics from the already-stored block if any;
                # otherwise compute fresh from the same context.
                existing_sf = payload.get("systemic_fragility")
                if not isinstance(existing_sf, dict):
                    market_ctx = payload.get("market_confirmation") or {}
                    struct_ctx = payload.get("structural_context") or {}
                    existing_sf = _compute_systemic_fragility(
                        market_ctx=market_ctx,
                        structural_ctx=struct_ctx,
                        related_events=related_events,
                    )

                new_sc = _compute_spatial_contagion(synth_ctx, systemic_fragility=existing_sf)
                payload["spatial_contagion"] = new_sc

                # Force SQLAlchemy to detect the JSON change (mutation tracking
                # on JSON columns is opt-in; reassigning the whole dict is the
                # safe portable path).
                r.structured_payload = payload
                upgraded += 1
                print(f"  ✓ {r.topic_code:<32s} schema={new_sc.get('schema_version')} "
                      f"orders={new_sc.get('order_counts')}")
            except Exception as exc:
                failed += 1
                print(f"  ✗ {r.topic_code}: {exc!s}"[:200])

        await db.commit()

    print()
    print(f"Done. upgraded={upgraded}  skipped={skipped}  failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
