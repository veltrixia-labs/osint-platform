"""
Targeted relabel of EXISTING active alerts whose stored title is now flagged
generic by the (fixed) headline_composer.is_generic_label — i.e. the flat synthetic
labels like "Hormuz oil sanction" / "Hormuz security attack". Recomposes a rich
headline from the row's OWN evidence_list, mirroring the live alert-manager path
(_resolve_display_label). Real, specific headlines are left untouched.

Acceptance is strict: a row is rewritten ONLY if its current label is generic/
source-like AND the composer yields a DIFFERENT, non-generic result. Otherwise it
is left as-is (no downgrade, no churn).

--execute writes a JSONL backup of every touched row to backups/ first, then sets
both target_label and metadata_json.display_title (the API serves display_title or
target_label). Run with the scheduler paused for a clean, contention-free pass.

Usage (repo root, DATABASE_URL / .env):
  py -3 scripts/relabel_generic_alerts.py             # DRY-RUN (preview, no writes)
  py -3 scripts/relabel_generic_alerts.py --execute   # backup + rewrite
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from db.database import AsyncSessionLocal
from db.models import AlertLog
from processor.headline_composer import compose_headline, is_generic_label
from analysis.pro_domain_config import infer_domain_from_topic
from jobs.alert_manager import _looks_like_source_label, _strip_distinctifiers, _normalize_alert_title

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("relabel_generic_alerts")


def _effective_label(a: AlertLog) -> str:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return _strip_distinctifiers(meta.get("display_title") or a.target_label or "")


def _needs_relabel(label: str) -> bool:
    """Same trigger the live composer uses: a source-slug OR generic label."""
    return bool(label) and (_looks_like_source_label(label) or is_generic_label(label))


async def main() -> None:
    p = argparse.ArgumentParser(description="Relabel generic active alerts via the composer")
    p.add_argument("--execute", action="store_true", help="Back up + rewrite (default: dry-run)")
    args = p.parse_args()

    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(AlertLog).where(AlertLog.suppressed == False)  # noqa: E712
        )).scalars().all()

        scanned = len(rows)
        generic = 0
        to_write: list[tuple] = []   # (AlertLog, old, new)
        skipped_no_better = 0

        for a in rows:
            old = _effective_label(a)
            if not _needs_relabel(old):
                continue
            generic += 1
            meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
            domain = infer_domain_from_topic(a.topic or "", text=old)
            new = _strip_distinctifiers(compose_headline(
                target_label=old,
                description=meta.get("description") or "",
                evidence_list=meta.get("evidence_list") or [],
                domain=domain,
            ) or "")
            # Accept ONLY a strictly better result: different + no longer generic.
            if (not new or _normalize_alert_title(new) == _normalize_alert_title(old)
                    or is_generic_label(new)):
                skipped_no_better += 1
                continue
            to_write.append((a, old, new))

        logger.info("scanned_active=%d  generic/source-like=%d  will_rewrite=%d  skipped_no_better=%d",
                    scanned, generic, len(to_write), skipped_no_better)
        for _, old, new in to_write[:40]:
            logger.info("  %-34s ->  %s", old[:34], new[:72])

        if not args.execute:
            logger.info("DRY-RUN: no writes. Re-run with --execute (scheduler paused).")
            return

        # Backup touched rows first.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
        os.makedirs(backup_dir, exist_ok=True)
        path = os.path.join(backup_dir, f"relabel_backup_{stamp}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for a, old, new in to_write:
                fh.write(json.dumps({"id": str(a.id), "old": old, "new": new,
                                     "target_label": a.target_label,
                                     "metadata_json": a.metadata_json}, default=str, ensure_ascii=False) + "\n")
        logger.info("Backup written: %s (%d rows)", path, len(to_write))

        for a, _old, new in to_write:
            meta = dict(a.metadata_json) if isinstance(a.metadata_json, dict) else {}
            a.target_label = new
            meta["display_title"] = new
            a.metadata_json = meta
            flag_modified(a, "metadata_json")
        await s.commit()
        logger.info("COMMITTED: rewrote %d active alert label(s).", len(to_write))


if __name__ == "__main__":
    asyncio.run(main())
