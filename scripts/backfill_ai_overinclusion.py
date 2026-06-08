"""
AI over-inclusion backfill (DRY-RUN by default).

Companion to fix-1 (commit 9d18c0f: omnivore tech feeds → tech_media group).
Fix-1 stopped NEW over-inclusion at ingest. This script cleans the EXISTING
ai_semiconductor_intelligence rows that the old step3 source-group fallback
(and the pre-`\b` substring path) mis-stamped.

Decision rule (matches the verified F1 simulation exactly):
  For each item currently category == 'ai_semiconductor_intelligence', re-evaluate
  with infer_topic_from_text(strict=True) using the CORRECTED post-fix-1
  source_group (the 5 omnivore feeds are now 'tech_media'; everything else keeps
  its stored group). Then:
    * re-eval == 'ai_semiconductor_intelligence'  -> KEEP (real AI: specialist
      feeds via step3, or any feed with AI/semiconductor content keywords).
    * re-eval is None                              -> NULLIFY (category/rough → None):
      geopolitical/general-news mislabels + omnivore tech noise. These are rows
      the CURRENT classifier would have dropped at the ingest gate.
    * re-eval == some other topic                  -> RESTAMP (F1 showed this == 0,
      handled defensively anyway).

Scope: `items` table ONLY. alert_logs are out of scope (only ~3 AI-stamped,
HOLD, and the Alert Stream is importance-ranked so a stale topic label is low-harm).

READ-ONLY by default. Writes ONLY with --apply, in batched bulk UPDATEs.
Before ANY write, a full reversible backup of every affected row
(id, source_id, old_category, old_rough_category) is written to a timestamped
JSON file in the repo root. Restore is therefore always possible.

RUN WITH THE SCHEDULER PAUSED for --apply (avoid lock contention on items);
dry-run is safe with the scheduler running.

Usage (repo root; DATABASE_URL / .env — prod DB):
  python scripts/backfill_ai_overinclusion.py                  # dry-run (backup + counts, NO writes)
  python scripts/backfill_ai_overinclusion.py --apply          # WRITE (after dry-run review + scheduler paused)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, update
from db.database import AsyncSessionLocal
from db.models import Item
from processor.lightweight_topic import infer_topic_from_text

AI = "ai_semiconductor_intelligence"
BATCH = 500

# Post-fix-1 source_group truth: these 5 feeds were moved to 'tech_media' in
# config/rss_sources.yaml (commit 9d18c0f). Items ingested BEFORE that still carry
# source_group='ai_semiconductor' in the DB, so we correct it here for re-eval.
TECH_MEDIA_FEEDS = {
    "techcrunch_feed", "arstechnica_feed", "mit_techreview_feed",
    "venturebeat_ai_feed", "tomshardware_feed",
}

KEEP, NULLIFY, RESTAMP = "KEEP", "NULLIFY", "RESTAMP"


def _corrected_source_group(item) -> str | None:
    if (item.source_id or "") in TECH_MEDIA_FEEDS:
        return "tech_media"
    return item.source_group


def _reeval(item) -> str | None:
    text = f"{item.title or ''} {item.summary or ''}".strip()
    return infer_topic_from_text(
        text,
        title=(item.title or None),
        source_group=_corrected_source_group(item),
        strict=True,
    )


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def main() -> None:
    p = argparse.ArgumentParser(description="Backfill AI over-inclusion (companion to fix-1)")
    p.add_argument("--apply", action="store_true", help="WRITE changes (batched bulk UPDATE)")
    args = p.parse_args()
    write = args.apply

    now = datetime.now(timezone.utc)
    mode = "APPLY (WRITES)" if write else "DRY-RUN (read-only)"
    print(f"\n=== AI over-inclusion backfill — {mode} ===")
    print("Rule: re-eval each ai_semiconductor item (corrected source_group, strict);")
    print("      None → nullify category, AI → keep. Scope: items table only.\n")

    nullify_ids: list = []
    restamp: dict[str, list] = {}
    backup: list[dict] = []
    counts: Counter = Counter()
    scanned = 0

    async with AsyncSessionLocal() as s:
        # ── READ PHASE (stream; read-only) ──────────────────────────────────
        stmt = select(Item).where(Item.category == AI)
        async for it in await s.stream_scalars(stmt.execution_options(yield_per=1000)):
            scanned += 1
            new = _reeval(it)
            if new == AI:
                counts[KEEP] += 1
                continue
            # record reversible backup for every row we will touch
            backup.append({
                "id": str(it.id),
                "source_id": it.source_id,
                "old_category": it.category,
                "old_rough_category": it.rough_category,
                "new_category": new,  # None or some other topic
                "title": (it.title or "")[:120],
            })
            if new is None:
                counts[NULLIFY] += 1
                nullify_ids.append(it.id)
            else:
                counts[RESTAMP] += 1
                restamp.setdefault(new, []).append(it.id)

        # ── BACKUP FILE (always written, even in dry-run) ───────────────────
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        backup_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", f"backfill_ai_overinclusion_backup_{stamp}.json")
        )
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump({"generated_at": now.isoformat(), "mode": mode, "rows": backup}, f, ensure_ascii=False, indent=2)
        print(f"backup written: {backup_path}  ({len(backup)} rows)")

        # ── WRITE PHASE (only --apply; batched bulk UPDATE) ─────────────────
        if write:
            wrote = 0
            for chunk in _chunks(nullify_ids, BATCH):
                await s.execute(
                    update(Item).where(Item.id.in_(chunk)).values(category=None, rough_category=None)
                )
                await s.commit()
                wrote += len(chunk)
            for new_cat, ids in restamp.items():
                for chunk in _chunks(ids, BATCH):
                    await s.execute(
                        update(Item).where(Item.id.in_(chunk)).values(category=new_cat, rough_category=new_cat)
                    )
                    await s.commit()
                    wrote += len(chunk)
            print(f"\n!! COMMITTED {wrote} row updates (batched).")

        # ── REPORT ──────────────────────────────────────────────────────────
        print(f"\n──────── RESULT ────────")
        print(f"scanned (ai-stamped):    {scanned}")
        print(f"KEEP (real AI):          {counts[KEEP]}")
        print(f"NULLIFY (→ None):        {counts[NULLIFY]}")
        print(f"RESTAMP (→ other):       {counts[RESTAMP]}")
        nb = Counter(b["source_id"] for b in backup if b["new_category"] is None)
        print(f"\n--- nullify by source_id ---")
        for sid, c in nb.most_common(20):
            print(f"  {str(sid):28s} {c}")
        print(f"\n=== {mode} complete." + ("" if write else " No data was modified.") + " ===")
        print(f"=== Backup ({len(backup)} rows) is at: {backup_path} ===")


if __name__ == "__main__":
    asyncio.run(main())
