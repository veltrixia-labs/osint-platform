"""
Backfill calibrated intensity_pct (+ re-aligned severity) on existing AlertLog rows.

Replays the per-strategic-domain decayed-baseline model over all stored alerts
(time-ordered) and writes:
  - metadata_json["intensity_pct"]  — distributed ratio-% (1.5x gate = 50%, >=3.0x = 100%)
  - severity                        — 3-tier gate from that % (watch/elevated/critical)

Sports/entertainment items are bucketed out (SPORTS_ENTERTAINMENT_DOMAIN) via the
headline guardrail, so they neither pollute a real domain's baseline nor get a
macro classification.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/backfill_intensity_pct.py            # apply
  py -3 scripts/backfill_intensity_pct.py --dry-run  # report only, no writes
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from analysis.intensity_pressure import (
    raw_intensity_from_alert,
    decayed_domain_baseline,
    percentage_from_ratio,
    severity_from_percentage,
)
from analysis.pro_domain_config import infer_domain_from_topic, SPORTS_ENTERTAINMENT_DOMAIN

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_intensity_pct")


def _alert_text(a: AlertLog) -> str:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return f"{a.target_label or ''} {meta.get('display_title', '')}"


async def main() -> None:
    p = argparse.ArgumentParser(description="Backfill calibrated intensity_pct + severity")
    p.add_argument("--dry-run", action="store_true", help="Report only; do not write")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(AlertLog).order_by(AlertLog.triggered_at.asc()))).scalars().all()
        logger.info("Loaded %d alert rows", len(rows))

        prior: dict[str, list] = defaultdict(list)
        updated = 0
        sev_changed = 0
        sports_suppressed = 0
        tier_counts: dict[str, int] = defaultdict(int)

        for a in rows:
            # Re-run the (guardrail-aware) classifier on EVERY row so sports noise
            # is reclassified out of the macro domains in the active DB state.
            domain = infer_domain_from_topic(a.topic or "", text=_alert_text(a))
            raw = raw_intensity_from_alert(a)
            baseline = decayed_domain_baseline(prior[domain], now=a.triggered_at)
            prior[domain].append(a)  # baseline = strictly prior activity

            # Data-Maturity Guardrail: cold-start (no baseline) stays UNCOMPUTED
            # (intensity_pct = None) so it is held out of the live feed; matured
            # rows get a real ratio-% + re-aligned severity.
            if baseline > 0:
                pct = round(percentage_from_ratio(raw / baseline), 1)
                sev = severity_from_percentage(pct)
                tier_counts[sev] += 1
            else:
                pct = None
                sev = None
                tier_counts["uncomputed"] += 1
            is_sports = domain == SPORTS_ENTERTAINMENT_DOMAIN

            if args.dry_run:
                if is_sports:
                    sports_suppressed += 1
                continue

            meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
            meta["intensity_pct"] = pct  # None for cold-start → dropped from feed
            meta["strategic_domain"] = domain  # record the guardrail classification
            a.metadata_json = meta
            flag_modified(a, "metadata_json")
            if sev is not None and a.severity != sev:
                a.severity = sev
                sev_changed += 1
            # Sports/entertainment = zero macro threat → strip from all strategic
            # views (Alert Stream, Risk Summary, Trend Flow) via suppression.
            if is_sports and not a.suppressed:
                a.suppressed = True
                sports_suppressed += 1
            updated += 1

        if not args.dry_run:
            await s.commit()

        logger.info(
            "%s: updated=%d severity_relabeled=%d sports_suppressed=%d",
            "DRY-RUN" if args.dry_run else "COMMITTED", updated, sev_changed, sports_suppressed,
        )
        logger.info("severity distribution: %s", dict(tier_counts))


if __name__ == "__main__":
    asyncio.run(main())
