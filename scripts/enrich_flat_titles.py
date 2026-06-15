"""
Targeted one-off: enrich flat / monotonous master-alert titles.

Active alerts whose headline is too generic ("Hormuz oil attack", "Hormuz
sanction escalation") — by is_generic_label, length < MIN_LEN, or an explicit
hit-list — are re-run through processor.headline_composer.compose_headline using
their (post-clustering, source-merged) evidence_list + description, so the master
shows a rich, context-blended headline instead of a flat stub.

NOTE: headline_composer is template/evidence-driven (mechanism + micro-geography +
trajectory, with a rich-source-headline fallback) — not an LLM. It synthesizes
from the absorbed sources already on the row.

Non-destructive aside from the title rewrite (target_label + display_title).
Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/enrich_flat_titles.py --dry-run
  py -3 scripts/enrich_flat_titles.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from analysis.pro_domain_config import infer_domain_from_topic
from processor.headline_composer import compose_headline, is_generic_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("enrich_flat_titles")

MIN_LEN = 40
HIT_LIST = {
    "hormuz oil attack",
    "hormuz sanction escalation",
    "hormuz energy sanction",
}


def _is_flat(title: str) -> bool:
    # NOTE: the `len < MIN_LEN` heuristic was dropped — it swept in good, specific
    # short titles ("French Navy seizes Russian oil tanker") that the composer then
    # mangled into fabricated/mismatched phrases. Restrict to genuinely generic
    # stubs (is_generic_label) + the explicit hit-list of known flat masters.
    t = (title or "").strip()
    return (not t) or is_generic_label(t) or t.lower() in HIT_LIST


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Preview only; no writes")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog).where(AlertLog.suppressed == False)  # noqa: E712
        )).scalars().all()

        enriched = 0
        skipped_no_gain = 0
        samples: list[tuple[str, str]] = []
        for a in rows:
            tl = a.target_label or ""
            if not _is_flat(tl):
                continue
            meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
            domain = infer_domain_from_topic(a.topic or "", text=tl)
            new = compose_headline(
                target_label=tl,
                description=meta.get("description") or "",
                evidence_list=meta.get("evidence_list") or [],
                domain=domain,
            )
            # Only accept a genuinely richer result (different + not itself flat).
            if not new or new == tl or _is_flat(new):
                skipped_no_gain += 1
                continue
            if len(samples) < 15:
                samples.append((tl[:38], new[:64]))
            if not args.dry_run:
                a.target_label = new
                meta["display_title"] = new
                a.metadata_json = meta
                flag_modified(a, "metadata_json")
            enriched += 1

        if not args.dry_run:
            await s.commit()

        logger.info(
            "%s: enriched=%d skipped_no_richer_candidate=%d (of %d active)",
            "DRY-RUN" if args.dry_run else "COMMITTED", enriched, skipped_no_gain, len(rows),
        )
        for old, new in samples:
            logger.info("  %-38s -> %s", old, new)


if __name__ == "__main__":
    asyncio.run(main())
