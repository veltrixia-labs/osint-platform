"""
Historical data reclamation: re-classify Markets-misclassified alert_logs under
the content-first taxonomy and re-headline flat cluster labels.

CONSERVATIVE by design: an alert is only moved out of Markets when the headline
text carries a STRONG content signal (>= 2 domain keyword hits). This avoids the
lightweight classifier's single-keyword false positives (e.g. an economy story
grazing one "defense" token). Re-headlining reuses processor.headline_composer.

Non-destructive (UPDATE only). Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/reclassify_historical.py --dry-run   # preview
  py -3 scripts/reclassify_historical.py             # apply
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
from processor.lightweight_topic import TOPIC_KEYWORD_RULES
from analysis.pro_domain_config import infer_domain_from_topic
from processor.headline_composer import compose_headline, is_generic_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reclassify_historical")

MIN_HITS = 2  # conservative: require a strong (>=2 keyword) content signal to move

# strategic domain id -> canonical alert_logs.topic code
STRATEGIC_TO_CANONICAL = {
    "energy_resource_risk": "ENERGY",
    "global_market_intelligence": "MARKET",
    "defense_technology": "DEFENSE",
    "crypto_geopolitics": "CRYPTO",
    "ai_semiconductor_intelligence": "AI_TECH",
    "supply_chain_intelligence": "SUPPLY_CHAIN",
}


def _best_domain(text: str) -> tuple[str | None, int]:
    low = (text or "").lower()
    best, best_hits = None, 0
    for code, keywords in TOPIC_KEYWORD_RULES:
        hits = sum(1 for kw in keywords if kw in low)
        if hits > best_hits:
            best, best_hits = code, hits
    return best, best_hits


async def main() -> None:
    p = argparse.ArgumentParser(description="Reclassify + re-headline historical alerts")
    p.add_argument("--dry-run", action="store_true", help="Preview only; no writes")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(AlertLog))).scalars().all()
        reclassified = 0
        reheadlined = 0
        moves: dict[str, int] = {}
        samples: list[str] = []

        for a in rows:
            meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
            text = f"{a.target_label or ''} {meta.get('display_title','')} {meta.get('description','')}"

            # 1. Re-classify ONLY currently-Markets alerts with a strong signal.
            if infer_domain_from_topic(a.topic or "", text=a.target_label or "") == "global_market_intelligence":
                best, hits = _best_domain(text)
                if best and best != "global_market_intelligence" and hits >= MIN_HITS:
                    new_topic = STRATEGIC_TO_CANONICAL.get(best)
                    if new_topic and new_topic != a.topic:
                        key = f"MARKET->{new_topic}"
                        moves[key] = moves.get(key, 0) + 1
                        if len(samples) < 8:
                            samples.append(f"[{hits}h {new_topic:13s}] {(a.target_label or '')[:46]}")
                        if not args.dry_run:
                            a.topic = new_topic
                        reclassified += 1

            # 2. Re-headline flat / generic cluster labels.
            if is_generic_label(a.target_label or ""):
                domain = infer_domain_from_topic(a.topic or "", text=a.target_label or "")
                new_title = compose_headline(
                    target_label=a.target_label or "",
                    description=meta.get("description") or "",
                    evidence_list=meta.get("evidence_list") or [],
                    domain=domain,
                )
                if new_title and new_title != (a.target_label or ""):
                    reheadlined += 1
                    if not args.dry_run:
                        a.target_label = new_title
                        meta["display_title"] = new_title
                        a.metadata_json = meta
                        flag_modified(a, "metadata_json")

        if not args.dry_run:
            await s.commit()

        mode = "DRY-RUN" if args.dry_run else "COMMITTED"
        logger.info("%s: reclassified=%d  reheadlined=%d  (of %d alerts)", mode, reclassified, reheadlined, len(rows))
        logger.info("moves: %s", moves)
        for x in samples:
            logger.info("  %s", x)


if __name__ == "__main__":
    asyncio.run(main())
