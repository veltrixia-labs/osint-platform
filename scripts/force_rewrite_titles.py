"""
Force-rewrite legacy flat master-alert titles into rich, context-aware headlines.

Targets ACTIVE (unsuppressed) alerts whose title contains "Hormuz" OR is shorter
than MIN_LEN chars (after stripping "(via …)" tags). Each is re-composed via
processor.headline_composer using the row's gathered (post-clustering) evidence,
and the enriched title is written back.

NOTE: headline_composer is template/evidence-driven (mechanism + micro-geography
+ trajectory, with a rich-source-headline fallback) — not an LLM. A result is
only accepted if it is meaningfully richer (different, >= MIN_LEN, not generic).

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/force_rewrite_titles.py --dry-run
  py -3 scripts/force_rewrite_titles.py
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
from jobs.alert_manager import _strip_distinctifiers

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("force_rewrite_titles")

MIN_LEN = 40


def _is_flat(title: str) -> bool:
    """A title is flat if (after stripping via-tags) it mentions Hormuz, is short,
    or is generic per the composer's own heuristic."""
    t = _strip_distinctifiers(title or "")
    return ("hormuz" in t.lower()) or (len(t) < MIN_LEN) or is_generic_label(t)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Preview only; no writes")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog).where(AlertLog.suppressed == False)  # noqa: E712
        )).scalars().all()

        rewritten = 0
        skipped = 0
        samples: list[tuple[str, str]] = []
        for a in rows:
            tl = _strip_distinctifiers(a.target_label or "")
            if not _is_flat(tl):
                continue
            meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
            domain = infer_domain_from_topic(a.topic or "", text=tl)
            new = _strip_distinctifiers(compose_headline(
                target_label=tl,
                description=meta.get("description") or "",
                evidence_list=meta.get("evidence_list") or [],
                domain=domain,
            ) or "")
            # Accept ONLY a genuinely richer result (different, long enough, not generic).
            if not new or new == (a.target_label or "") or len(new) < MIN_LEN or is_generic_label(new):
                skipped += 1
                continue
            if len(samples) < 20:
                samples.append((tl[:38], new[:64]))
            if not args.dry_run:
                a.target_label = new
                meta["display_title"] = new
                a.metadata_json = meta
                flag_modified(a, "metadata_json")
            rewritten += 1

        if not args.dry_run:
            await s.commit()

        logger.info(
            "%s: rewritten=%d skipped_no_richer_candidate=%d (of %d active)",
            "DRY-RUN" if args.dry_run else "COMMITTED", rewritten, skipped, len(rows),
        )
        for old, new in samples:
            logger.info("  %-38s -> %s", old, new)


if __name__ == "__main__":
    asyncio.run(main())
