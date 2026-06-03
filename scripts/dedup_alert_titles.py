"""
Find ACTIVE alerts that share an identical display_title and re-run each through
the (fixed) headline_composer so every row gets a distinct, angle-specific headline
drawn from its OWN evidence. A final per-run uniqueness guard guarantees no two
active rows end up identical (fallback: a distinct unused evidence title, then a
source-anchor suffix).

--execute writes a JSONL backup of touched rows to backups/ first, then sets both
target_label and metadata_json.display_title.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/dedup_alert_titles.py             # DRY-RUN (preview, no writes)
  py -3 scripts/dedup_alert_titles.py --execute   # backup + rewrite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, desc
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from processor.headline_composer import compose_headline, is_generic_label
from analysis.pro_domain_config import infer_domain_from_topic
from jobs.alert_manager import _normalize_alert_title, _strip_distinctifiers

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("dedup_alert_titles")


def _meta(a):
    return a.metadata_json if isinstance(a.metadata_json, dict) else {}


def _label(a) -> str:
    return _strip_distinctifiers(_meta(a).get("display_title") or a.target_label or "")


def _evidence(a):
    return [e for e in (_meta(a).get("evidence_list") or []) if isinstance(e, dict)]


def _lead_domain(a) -> str:
    for e in _evidence(a):
        d = (e.get("domain") or "").replace("www.", "").strip()
        if d:
            return d
    return ""


def _recompose(a) -> str:
    label = _label(a)
    domain = infer_domain_from_topic(a.topic or "", text=label)
    return _strip_distinctifiers(compose_headline(
        target_label=label,
        description=_meta(a).get("description") or "",
        evidence_list=_evidence(a),
        domain=domain,
    ) or "")


async def main() -> None:
    p = argparse.ArgumentParser(description="De-duplicate identical active alert titles")
    p.add_argument("--execute", action="store_true", help="Back up + rewrite (default: dry-run)")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog).where(AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
        )).scalars().all()

        groups = defaultdict(list)
        for a in rows:
            groups[_normalize_alert_title(_label(a))].append(a)
        dup_groups = [v for k, v in groups.items() if len(v) > 1]

        # Reserve every NON-duplicated active title so we never collide into one.
        used = {k for k, v in groups.items() if len(v) == 1}
        changes: list[tuple] = []   # (AlertLog, old, new)

        for members in dup_groups:
            for a in members:
                old = _label(a)
                new = _recompose(a)
                # Uniqueness guard: if recompose collides with an already-assigned
                # title, pick a distinct unused evidence headline; else anchor it.
                if not new or _normalize_alert_title(new) in used:
                    alt = next((t for t in (_strip_distinctifiers((e.get("title") or "")) for e in _evidence(a))
                                if t and not is_generic_label(t) and _normalize_alert_title(t) not in used), None)
                    if alt:
                        new = alt
                    else:
                        dom = _lead_domain(a)
                        new = f"{new or old} (via {dom})" if dom else f"{new or old} #{len(changes)+1}"
                used.add(_normalize_alert_title(new))
                if _normalize_alert_title(new) != _normalize_alert_title(old):
                    changes.append((a, old, new))

        logger.info("active=%d  duplicate_groups=%d  rows_to_rewrite=%d",
                    len(rows), len(dup_groups), len(changes))
        for _, old, new in changes:
            logger.info("  %-46s ->  %s", old[:46], new[:78])

        if not args.execute:
            logger.info("DRY-RUN: no writes. Re-run with --execute.")
            return

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
        os.makedirs(backup_dir, exist_ok=True)
        path = os.path.join(backup_dir, f"dedup_titles_backup_{stamp}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for a, old, new in changes:
                fh.write(json.dumps({"id": str(a.id), "old": old, "new": new,
                                     "target_label": a.target_label, "metadata_json": a.metadata_json},
                                    default=str, ensure_ascii=False) + "\n")
        logger.info("Backup written: %s (%d rows)", path, len(changes))

        for a, _old, new in changes:
            meta = dict(_meta(a))
            a.target_label = new
            meta["display_title"] = new
            a.metadata_json = meta
            flag_modified(a, "metadata_json")
        await s.commit()
        logger.info("COMMITTED: rewrote %d duplicate alert title(s).", len(changes))


if __name__ == "__main__":
    asyncio.run(main())
