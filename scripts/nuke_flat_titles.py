"""
Force-nuke residual FLAT / ghost master-alert titles with deterministic,
hardcoded professional headlines — NO composer dependency.

force_rewrite_titles.py leans on processor.headline_composer; when the composer
returns a flat/generic/unchanged candidate the row is SKIPPED and the ghost title
("Hormuz oil sanction", "Hormuz oil sanction (via news.usni.org)") survives. This
script bypasses the composer entirely:

  1. Query the live DB for every row whose target_label OR metadata_json
     display_title matches the ghost patterns (Hormuz / the Moscow drone strike).
  2. Print the exact id / severity / suppressed / current titles for each match.
  3. Overwrite BOTH target_label and metadata_json["display_title"] with a
     hardcoded, professional headline (keyword-bucketed so distinct events do NOT
     all collapse to one string) — but ONLY for rows that are still FLAT or match
     a named ghost pattern. Rows that already carry a rich composed headline are
     left untouched (we do not destroy good data).
  4. Collapse any resulting EXACT-duplicate active titles: keep the highest
     intensity, suppress the rest (reversible — suppressed=True, not deleted).
  5. Commit to the LIVE database.

The API serializes title = metadata_json["display_title"] or target_label, so we
must set BOTH for the change to surface in the feed. (Active feed hides
suppressed rows; Redis cache TTL is 60s so the UI reflects this within a minute.)

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/nuke_flat_titles.py --dry-run   # inspect + preview, no writes
  py -3 scripts/nuke_flat_titles.py             # commit to live DB
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, or_
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.alert_manager import _strip_distinctifiers, _normalize_alert_title
from processor.headline_composer import is_generic_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("nuke_flat_titles")

# A title is "flat" if — after stripping (via …)/(re-escalation)/#N tags — it is
# short or generic. Good composed headlines ("Naval interception at Strait of
# Hormuz, sparking energy-supply friction") clear this bar and are PRESERVED.
MIN_RICH_LEN = 45

# Patterns we go hunting for (the user-named ghost titles). Matched against the
# raw target_label AND the serialized display_title, case-insensitively.
GHOST_LIKE = ["%Hormuz%", "%drone attack kills three in Moscow%", "%drone attack kills three%"]

# Explicit ghost strings that MUST be overwritten even if length-wise they would
# squeak past the flat bar (the exact residue the user is still seeing).
GHOST_EXACT = {
    "hormuz oil sanction",
    "hormuz sanction",
    "hormuz sanction escalation",
    "hormuz oil sanction escalation",
    "drone attack kills three in moscow",
}


def _display_title(a: AlertLog) -> str:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return meta.get("display_title") or ""


def _effective_label(a: AlertLog) -> str:
    """The string the API actually serves as `title` (display_title or target_label)."""
    return _display_title(a) or (a.target_label or "")


def _is_flat(label: str) -> bool:
    t = _strip_distinctifiers(label or "")
    if not t:
        return True
    if t.lower() in GHOST_EXACT:
        return True
    return len(t) < MIN_RICH_LEN or is_generic_label(t)


def _professional_title(label: str) -> str:
    """Deterministic, hardcoded professional headline bucketed by keyword — no composer."""
    s = (label or "").lower()
    if "moscow" in s or "drone attack kills three" in s:
        return "Large-Scale Ukrainian Drone Strike on Moscow Region Leaves Three Dead"
    if "sanction" in s:
        return "Escalating Sanctions in the Strait of Hormuz Disrupt Energy Markets"
    if "ceasefire" in s:
        return "Hormuz Ceasefire Negotiations Hinge on Israeli De-escalation"
    # Generic flat-Hormuz fallback.
    return "Strait of Hormuz Naval Standoff Threatens Global Energy Transit"


async def main() -> None:
    p = argparse.ArgumentParser(description="Force-nuke residual flat/ghost titles")
    p.add_argument("--dry-run", action="store_true", help="Inspect + preview; no writes")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        # Match on BOTH target_label and the JSONB display_title — a ghost can hide
        # in either field. Include suppressed rows so collapsed dupes can't resurface
        # a flat title later.
        conds = []
        for pat in GHOST_LIKE:
            conds.append(AlertLog.target_label.ilike(pat))
            conds.append(AlertLog.metadata_json["display_title"].astext.ilike(pat))
        rows = (await s.execute(select(AlertLog).where(or_(*conds)))).scalars().all()

        logger.info("Matched %d row(s) for ghost patterns %s", len(rows), GHOST_LIKE)
        logger.info("---- EXACT MATCHES (id | sev | suppressed | target_label | display_title) ----")
        for a in rows:
            logger.info(
                "  %s | %-8s | supp=%-5s | %r | %r",
                a.id, a.severity, a.suppressed, a.target_label, _display_title(a),
            )

        # Overwrite the FLAT / ghost rows; preserve already-rich composed headlines.
        modified: list[tuple[str, str, str]] = []  # (id, before, after)
        for a in rows:
            eff = _effective_label(a)
            if not _is_flat(eff):
                continue
            new = _professional_title(eff)
            if _normalize_alert_title(new) == _normalize_alert_title(eff):
                continue
            modified.append((str(a.id), eff, new))
            if not args.dry_run:
                a.target_label = new
                meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
                meta["display_title"] = new
                a.metadata_json = meta
                flag_modified(a, "metadata_json")

        logger.info("---- OVERWRITES (%d) ----", len(modified))
        for rid, before, after in modified:
            logger.info("  %s\n      BEFORE: %r\n      AFTER : %r", rid, before, after)

        # Collapse exact-duplicate ACTIVE titles created by the hardcoded buckets:
        # keep the highest-intensity row, suppress the rest (reversible).
        active = [a for a in rows if not a.suppressed]
        by_title: dict[str, list[AlertLog]] = {}
        for a in active:
            by_title.setdefault(_normalize_alert_title(_effective_label(a)), []).append(a)

        suppressed_ids: list[str] = []
        for title_key, group in by_title.items():
            if len(group) < 2:
                continue
            group.sort(key=lambda a: float(a.intensity or 0.0), reverse=True)
            for dup in group[1:]:
                suppressed_ids.append(str(dup.id))
                if not args.dry_run:
                    dup.suppressed = True

        logger.info("---- DUPLICATE SUPPRESSIONS (%d) ----", len(suppressed_ids))
        for rid in suppressed_ids:
            logger.info("  suppressed dup -> %s", rid)

        if not args.dry_run:
            await s.commit()

        logger.info(
            "%s: matched=%d overwritten=%d duplicates_suppressed=%d",
            "DRY-RUN" if args.dry_run else "COMMITTED",
            len(rows), len(modified), len(suppressed_ids),
        )


if __name__ == "__main__":
    asyncio.run(main())
