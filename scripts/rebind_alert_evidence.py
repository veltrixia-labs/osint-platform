"""
Rebind existing active alerts' evidence_list to the new coherence standard:
keep only evidence items that share a NON-GEO (specific-angle) token with the
alert's own headline, dropping single-anchor grab-bag items bound only by a geo
anchor (the legacy trend-grouping pollution). Conservative — it only PRUNES; it
never invents evidence. Every alert keeps >=1 source (its closest match if all
else is dropped).

--execute writes a JSONL backup of touched rows to backups/ first, then updates
metadata_json.evidence_list / supporting_events_count / domain_count. Run with the
scheduler paused.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/rebind_alert_evidence.py             # DRY-RUN (preview diff, no writes)
  py -3 scripts/rebind_alert_evidence.py --execute   # backup + rewrite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, desc
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.alert_manager import _event_tokens, _strip_distinctifiers
from analysis.clustering import GEO_ENTITIES

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rebind_alert_evidence")

_GEO = {w for g in GEO_ENTITIES for w in g.split()}
MIN_EVIDENCE = 2  # nothing to prune below this


def _meta(a):
    return a.metadata_json if isinstance(a.metadata_json, dict) else {}


def _headline_tokens(a) -> set:
    m = _meta(a)
    return _event_tokens(f"{a.target_label or ''} {m.get('display_title', '')}")


def _ev(a):
    return [e for e in (_meta(a).get("evidence_list") or []) if isinstance(e, dict)]


def _split(a):
    """Return (kept, dropped) evidence dicts using the SAME test the audit flags as
    over-merge: drop an item only if it shares ONLY a geo anchor (or nothing) with
    the rest of the cluster centroid; keep the coherent core (incl. same-theater
    corroboration that shares non-geo with any cluster-mate). Guarantee >=1 kept."""
    ev = _ev(a)
    toks = [_event_tokens(_strip_distinctifiers(str(e.get("title") or ""))) for e in ev]
    kept, dropped = [], []
    for i, e in enumerate(ev):
        centroid = set().union(*(toks[j] for j in range(len(toks)) if j != i)) if len(toks) > 1 else set()
        if (toks[i] & centroid) - _GEO:    # shares non-geo context with the cluster
            kept.append(e)
        else:
            dropped.append(e)
    if not kept and ev:                    # pure grab-bag: keep the item closest to the headline
        htok = _headline_tokens(a)
        bi = max(range(len(ev)), key=lambda i: len(toks[i] & htok))
        kept = [ev[bi]]
        dropped = [e for k, e in enumerate(ev) if k != bi]
    return kept, dropped


async def main() -> None:
    p = argparse.ArgumentParser(description="Rebind alert evidence to the coherence standard")
    p.add_argument("--execute", action="store_true", help="Back up + rewrite (default: dry-run)")
    p.add_argument("--show", type=int, default=15, help="How many changed alerts to print")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog).where(AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
        )).scalars().all()

        changed = []
        ev_before = ev_after = 0
        for a in rows:
            ev = _ev(a)
            ev_before += len(ev)
            if len(ev) < MIN_EVIDENCE:
                ev_after += len(ev)
                continue
            kept, dropped = _split(a)
            ev_after += len(kept)
            if dropped:
                changed.append((a, kept, dropped))

        n = len(rows) or 1
        print(f"active alerts scanned:        {len(rows)}")
        print(f"alerts pruned:                {len(changed)} ({100*len(changed)/n:.0f}%)")
        print(f"evidence items before:        {ev_before}")
        print(f"evidence items after:         {ev_after}   (dropped {ev_before-ev_after})")

        print(f"\n--- sample diffs (first {args.show} pruned alerts) ---")
        for a, kept, dropped in changed[: args.show]:
            hl = (_meta(a).get("display_title") or a.target_label or "")[:60]
            print(f"\n  [{a.topic}] {hl!r}  ({len(kept)} kept / {len(dropped)} dropped)")
            for e in dropped[:4]:
                print(f"      DROP  {str(e.get('title') or '')[:70]!r}")

        if not args.execute:
            print("\nDRY-RUN: no writes. Re-run with --execute (scheduler paused).")
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
        os.makedirs(backup_dir, exist_ok=True)
        path = os.path.join(backup_dir, f"rebind_evidence_backup_{stamp}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for a, kept, dropped in changed:
                fh.write(json.dumps({"id": str(a.id), "metadata_json": a.metadata_json},
                                    default=str, ensure_ascii=False) + "\n")
        logger.info("Backup written: %s (%d rows)", path, len(changed))

        for a, kept, _dropped in changed:
            m = dict(_meta(a))
            m["evidence_list"] = kept
            m["domain_count"] = len({urlparse(e.get("url") or e.get("link") or "").netloc
                                     for e in kept if (e.get("url") or e.get("link"))})
            a.metadata_json = m
            a.supporting_events_count = len(kept)
            flag_modified(a, "metadata_json")
        await s.commit()
        logger.info("COMMITTED: rebound evidence on %d alert(s).", len(changed))


if __name__ == "__main__":
    asyncio.run(main())
