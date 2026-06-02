"""
READ-ONLY clustering-quality audit. Makes NO writes (SELECT only, no commit).

Samples active alerts and measures, for each, how tightly its merged evidence_list
coheres with the master headline — using the SAME production token/similarity
functions (jobs.alert_manager._event_tokens / _event_similarity) so the audit
mirrors the live clustering guard. Flags "loose" evidence (a source whose title
barely overlaps the master — the classic shared-anchor leak, e.g. only "Hormuz")
and clusters that span multiple distinct GEO anchors.

Usage (repo root, DATABASE_URL / .env):  py -3 scripts/audit_clustering.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, desc

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.alert_manager import _event_tokens, _event_similarity, _strip_distinctifiers
from analysis.clustering import GEO_ENTITIES, extract_entities

LOOSE_SIM = 0.12          # evidence title this far below the master headline = loosely bound
MIN_EVIDENCE = 3          # only audit clusters with real corroboration


def _master_text(a: AlertLog) -> str:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return f"{a.target_label or ''} {meta.get('display_title', '')}"


def _evidence(a: AlertLog) -> list:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return [e for e in (meta.get("evidence_list") or []) if isinstance(e, dict)]


async def main() -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog)
            .where(AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
            .limit(400)
        )).scalars().all()

    audited = 0
    clusters_with_loose = 0
    total_evidence = 0
    total_loose = 0
    multi_geo = 0
    offenders: list[tuple] = []

    for a in rows:
        ev = _evidence(a)
        if len(ev) < MIN_EVIDENCE:
            continue
        audited += 1
        master = _event_tokens(_master_text(a))
        if not master:
            continue

        loose = []
        geos: set[str] = set()
        for e in ev:
            title = _strip_distinctifiers(str(e.get("title") or ""))
            etok = _event_tokens(title)
            sim = _event_similarity(master, etok)
            shared = master & etok
            geos |= {t for t in title.lower().split() if t in GEO_ENTITIES}
            total_evidence += 1
            if sim < LOOSE_SIM:
                total_loose += 1
                loose.append((round(sim, 3), sorted(shared)[:4], title[:70]))

        if len(geos) > 1:
            multi_geo += 1
        if loose:
            clusters_with_loose += 1
            offenders.append((len(loose), len(ev), a.topic, (a.target_label or "")[:60], geos, loose))

    print("=" * 78)
    print("CLUSTERING QUALITY AUDIT  (READ-ONLY — no DB writes)")
    print("=" * 78)
    print(f"Active alerts scanned (latest 400):        {len(rows)}")
    print(f"Clusters audited (>= {MIN_EVIDENCE} evidence):          {audited}")
    print(f"  ...with >=1 loosely-bound source (<{LOOSE_SIM}): {clusters_with_loose}"
          f" ({(100*clusters_with_loose/audited):.0f}%)" if audited else "")
    print(f"  ...spanning >1 distinct GEO anchor:        {multi_geo}")
    print(f"Evidence items inspected:                   {total_evidence}")
    print(f"  ...loosely bound to their master:         {total_loose}"
          f" ({(100*total_loose/total_evidence):.1f}%)" if total_evidence else "")

    offenders.sort(reverse=True)
    print("\nTOP 12 LOOSEST CLUSTERS (most weakly-bound evidence):")
    for n_loose, n_ev, topic, label, geos, loose in offenders[:12]:
        print(f"\n  [{topic}] {label!r}  ({n_loose}/{n_ev} loose; geos={sorted(geos)})")
        for sim, shared, title in loose[:4]:
            print(f"      sim={sim:<5} shared={shared} :: {title!r}")


if __name__ == "__main__":
    asyncio.run(main())
