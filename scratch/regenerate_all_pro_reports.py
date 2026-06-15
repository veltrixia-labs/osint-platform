"""
Batch-regenerate every existing pro_structural Report so the v2
spatial_contagion (with order field + 2-hop downstream nodes) is consistent
across the whole corpus.

Strategy:
  • For each pro_structural Report in the DB, extract its anchor alert_id
    from structured_payload.signal.alert_id.
  • Invoke `run_pro_structural_report_generation(alert_id, domain_id,
    force_rebuild=True)` so the in-place update writes the new schema_version=v2
    payload over the existing row (UPDATE, not INSERT — see compile dedup).
  • Reports whose anchor alert has been pruned out fall back to the
    domain-only generation path, which re-anchors on the latest live alert.
  • Failure on one report does not abort the run.

Idempotent: re-running yields no-op (compile dedup) once every brief is v2.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, desc
from db.database import AsyncSessionLocal
from db.models import Report
from jobs.pro_report_generator import run_pro_structural_report_generation


async def main() -> int:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Report)
            .where(Report.report_type == "pro_structural")
            .order_by(desc(Report.created_at))
        )
        rows = (await db.execute(stmt)).scalars().all()

    print(f"Found {len(rows)} pro_structural reports.")
    if not rows:
        return 0

    ok = 0
    skipped = 0
    failed = 0
    v2_after = 0
    per_domain: dict[str, int] = {}

    for i, r in enumerate(rows, start=1):
        domain = r.topic_code or "global"
        payload = r.structured_payload or {}
        if not isinstance(payload, dict):
            payload = {}
        signal_block = payload.get("signal") or {}
        alert_id = signal_block.get("alert_id") if isinstance(signal_block, dict) else None

        try:
            new_report = await run_pro_structural_report_generation(
                alert_id=str(alert_id) if alert_id else None,
                domain_id=domain,
                report_type=r.report_type,
                force_rebuild=True,
            )
            ok += 1
            per_domain[domain] = per_domain.get(domain, 0) + 1
            # Inspect resulting schema
            sp = new_report.structured_payload or {}
            sc = sp.get("spatial_contagion") if isinstance(sp, dict) else None
            if isinstance(sc, dict) and sc.get("schema_version") == "spatial_contagion_v2":
                v2_after += 1
        except Exception as exc:
            failed += 1
            print(f"  [{i:>3}/{len(rows)}] FAIL {domain} alert={alert_id}: {exc!s}"[:200])
            continue

        if i % 25 == 0 or i == len(rows):
            print(f"  [{i:>3}/{len(rows)}] processed (ok={ok} fail={failed} v2={v2_after})")

    print()
    print(f"Done. ok={ok}  failed={failed}  skipped={skipped}  v2_payloads={v2_after}/{len(rows)}")
    for d, n in sorted(per_domain.items()):
        print(f"  {d:<32s} {n}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
