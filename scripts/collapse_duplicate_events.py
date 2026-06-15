"""
One-off cleanup: collapse same-event duplicate alerts from the last N hours into a
single master row (merging their corroborating sources), so the live stream stops
showing redundant near-duplicates (e.g. the "Bessent / Iran crypto seizure" spam).

Uses the SAME event-similarity model as the live clustering guard in
jobs.alert_manager (topic + Jaccard token overlap). For each cluster of >1 active
alert it keeps the highest-intensity row as master, merges every member's
evidence_list into it, and SUPPRESSES the rest (reversible — suppressed=True, not
deleted). The feed already hides suppressed rows, so the UI cleans up instantly.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/collapse_duplicate_events.py --dry-run   # preview clusters
  py -3 scripts/collapse_duplicate_events.py             # apply
  py -3 scripts/collapse_duplicate_events.py --hours 12  # window (default 12)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, desc
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.alert_manager import (
    _event_tokens,
    _event_similarity,
    _raw_intensity_for_alert,
    CLUSTER_SIM_THRESHOLD,
    CLUSTER_MAX_EVIDENCE,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("collapse_duplicate_events")


def _alert_text(a: AlertLog) -> str:
    # Headline only — descriptions share boilerplate vocabulary that falsely
    # inflates similarity and chains distinct events together.
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return f"{a.target_label or ''} {meta.get('display_title', '')}"


def _evidence(a: AlertLog) -> list:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return list(meta.get("evidence_list") or [])


async def main() -> None:
    p = argparse.ArgumentParser(description="Collapse same-event duplicate alerts")
    p.add_argument("--hours", type=int, default=12, help="Look-back window (default 12)")
    p.add_argument("--dry-run", action="store_true", help="Preview only; no writes")
    args = p.parse_args()

    window_start = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog)
            .where(AlertLog.triggered_at >= window_start, AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
        )).scalars().all()
        logger.info("Loaded %d active alerts in the last %dh", len(rows), args.hours)

        # Greedy clustering by (topic + similarity to a cluster representative).
        clusters: list[dict] = []
        for a in rows:
            toks = _event_tokens(_alert_text(a))
            if not toks:
                continue
            best, best_sim = None, 0.0
            for c in clusters:
                # No topic silo — cluster purely on title similarity, so the same
                # event split across topics (DEFENSE vs MARKET) collapses together.
                sim = _event_similarity(toks, c["rep_tokens"])
                if sim > best_sim:
                    best, best_sim = c, sim
            if best is not None and best_sim >= CLUSTER_SIM_THRESHOLD:
                best["members"].append(a)
            else:
                clusters.append({"topic": a.topic, "rep_tokens": toks, "members": [a]})

        dupes = [c for c in clusters if len(c["members"]) > 1]
        logger.info("Found %d multi-alert event cluster(s) to collapse", len(dupes))

        collapsed_rows = 0
        for c in dupes:
            # Master = highest raw intensity; tie → earliest (the originating row).
            members = sorted(
                c["members"],
                key=lambda a: (_raw_intensity_for_alert(a), -(a.triggered_at.timestamp())),
                reverse=True,
            )
            master = members[0]
            others = members[1:]

            m_meta = dict(master.metadata_json) if isinstance(master.metadata_json, dict) else {}
            merged = _evidence(master)
            seen = {(e.get("url") or e.get("link") or e.get("title") or "").strip()
                    for e in merged if isinstance(e, dict)}
            for o in others:
                for ev in _evidence(o):
                    if not isinstance(ev, dict):
                        continue
                    key = (ev.get("url") or ev.get("link") or ev.get("title") or "").strip()
                    if key and key in seen:
                        continue
                    merged.append(ev)
                    if key:
                        seen.add(key)

            logger.info(
                "  cluster[%s] master=%r (+%d sources) suppresses %d: %s",
                c["topic"], (master.target_label or "")[:48], len(merged), len(others),
                [(o.target_label or "")[:34] for o in others],
            )

            if args.dry_run:
                continue

            m_meta["evidence_list"] = merged[:CLUSTER_MAX_EVIDENCE]
            m_meta["corroboration_count"] = int(m_meta.get("corroboration_count", 0) or 0) + len(others)
            m_meta["last_corroborated_at"] = datetime.now(timezone.utc).isoformat()
            master.metadata_json = m_meta
            master.supporting_events_count = len(m_meta["evidence_list"])
            flag_modified(master, "metadata_json")
            for o in others:
                o.suppressed = True
                collapsed_rows += 1

        if not args.dry_run:
            await s.commit()

        logger.info(
            "%s: clusters_collapsed=%d rows_suppressed=%d",
            "DRY-RUN" if args.dry_run else "COMMITTED", len(dupes), collapsed_rows,
        )


if __name__ == "__main__":
    asyncio.run(main())
