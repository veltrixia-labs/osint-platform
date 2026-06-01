"""
Regenerate high-context Alert headlines on existing AlertLog rows.

Replays the headline composer (processor/headline_composer) over every stored
alert's `metadata_json.evidence_list` + topic, replacing flat generic cluster
labels ("Iran oil attack") with distinct, context-blended headlines. A 12-hour
de-duplication guard appends a source-driven distinctifier whenever two alerts in
the same window would otherwise resolve to a byte-identical title.

Writes: AlertLog.target_label  and  metadata_json.display_title.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/regenerate_headlines.py            # apply
  py -3 scripts/regenerate_headlines.py --dry-run  # preview only
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from analysis.pro_domain_config import infer_domain_from_topic
from processor.headline_composer import compose_headline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("regenerate_headlines")

DEDUP_WINDOW = timedelta(hours=12)


def _norm(t: str) -> str:
    return " ".join((t or "").strip().lower().split())


def _distinctify(title: str, evidence_list) -> str:
    dom = ""
    for ev in (evidence_list or []):
        if isinstance(ev, dict):
            d = (ev.get("domain") or "").strip()
            if d:
                dom = d.replace("www.", "")
                break
    return f"{title} (via {dom})" if dom else f"{title} (re-escalation)"


async def main() -> None:
    p = argparse.ArgumentParser(description="Regenerate high-context alert headlines")
    p.add_argument("--dry-run", action="store_true", help="Preview only; no writes")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(AlertLog).order_by(AlertLog.triggered_at.asc()))).scalars().all()
        logger.info("Loaded %d alert rows", len(rows))

        seen: dict[str, object] = {}  # normalized title -> last triggered_at
        updated = 0
        samples: list[tuple[str, str]] = []

        for a in rows:
            meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
            evidence = meta.get("evidence_list") or []
            domain = infer_domain_from_topic(a.topic or "", text=a.target_label or "")
            title = compose_headline(
                target_label=a.target_label or "",
                description=meta.get("description") or "",
                evidence_list=evidence,
                domain=domain,
            )

            # 12-hour identical-title guard.
            key = _norm(title)
            prev = seen.get(key)
            if prev is not None and a.triggered_at and (a.triggered_at - prev) <= DEDUP_WINDOW:
                title = _distinctify(title, evidence)
                key = _norm(title)
            seen[key] = a.triggered_at

            if title and title != (a.target_label or ""):
                if len(samples) < 8:
                    samples.append(((a.target_label or "")[:30], title[:80]))
                if not args.dry_run:
                    a.target_label = title
                    meta["display_title"] = title
                    a.metadata_json = meta
                    flag_modified(a, "metadata_json")
                updated += 1

        if not args.dry_run:
            await s.commit()

        logger.info("%s: headlines rewritten=%d / %d", "DRY-RUN" if args.dry_run else "COMMITTED", updated, len(rows))
        for old, new in samples:
            logger.info("  %-30s -> %s", old, new)


if __name__ == "__main__":
    asyncio.run(main())
