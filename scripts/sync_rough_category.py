"""
rough_category sync (DRY-RUN by default).

Follow-up to backfill_ai_overinclusion.py. That backfill nulled `category` for
5,587 mislabeled AI items, but `rough_category` (Stage-1 rough label) was a
SEPARATE column on rows whose `category` was already non-AI, so 231 rows still
carry rough_category='ai_semiconductor_intelligence' while category says
otherwise. These leak back as "AI" through signal_job.py (category OR
rough_category filter) and clustering.py (category or rough_category fallback).

Rule (rough_category must follow category):
  * category is a concrete topic  -> rough_category := category   (group CONCRETE)
  * category is None / 'none' / '' -> rough_category := None       (group NONE)
Scope: ONLY rows where rough_category='ai_semiconductor_intelligence'
       AND category != 'ai_semiconductor_intelligence'. The 1,006 genuine-AI rows
       (category=AI) are untouched.

READ-ONLY by default. Writes ONLY with --apply, batched. A full JSON backup
(id, old_category, old_rough_category, new_rough_category) is written before any
write so the change is fully reversible.

RUN WITH THE SCHEDULER PAUSED for --apply.

Usage (repo root; DATABASE_URL / .env — prod DB):
  python scripts/sync_rough_category.py            # dry-run (backup + counts, NO writes)
  python scripts/sync_rough_category.py --apply     # WRITE (scheduler paused)
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

from sqlalchemy import select, update, or_
from db.database import AsyncSessionLocal
from db.models import Item

AI = "ai_semiconductor_intelligence"
BATCH = 500
NONE_LIKE = {"none", "", "misc"}


def _is_none_like(cat) -> bool:
    return cat is None or (isinstance(cat, str) and cat.strip().lower() in NONE_LIKE)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def main() -> None:
    p = argparse.ArgumentParser(description="Sync rough_category to category for stale AI rough labels")
    p.add_argument("--apply", action="store_true", help="WRITE changes (batched bulk UPDATE)")
    args = p.parse_args()
    write = args.apply

    now = datetime.now(timezone.utc)
    mode = "APPLY (WRITES)" if write else "DRY-RUN (read-only)"
    print(f"\n=== rough_category sync — {mode} ===")
    print("Rule: rough_category follows category. Scope: rough=AI & category!=AI.\n")

    # group_concrete: {new_rough_value: [ids]}; group_none: [ids]
    concrete_by_val: dict[str, list] = {}
    none_ids: list = []
    backup: list[dict] = []
    counts: Counter = Counter()

    async with AsyncSessionLocal() as s:
        stmt = (
            select(Item.id, Item.category, Item.rough_category)
            .where(Item.rough_category == AI)
            .where(or_(Item.category != AI, Item.category.is_(None)))
        )
        rows = (await s.execute(stmt)).all()
        for r in rows:
            if _is_none_like(r.category):
                new_rough = None
                none_ids.append(r.id)
                counts["NONE"] += 1
            else:
                new_rough = r.category
                concrete_by_val.setdefault(r.category, []).append(r.id)
                counts["CONCRETE"] += 1
            backup.append({
                "id": str(r.id),
                "old_category": r.category,
                "old_rough_category": r.rough_category,
                "new_rough_category": new_rough,
            })

        # backup file (always, even dry-run)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        backup_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", f"sync_rough_category_backup_{stamp}.json")
        )
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump({"generated_at": now.isoformat(), "mode": mode, "rows": backup}, f, ensure_ascii=False, indent=2)
        print(f"backup written: {backup_path}  ({len(backup)} rows)")

        if write:
            wrote = 0
            # group NONE: rough_category := None
            for chunk in _chunks(none_ids, BATCH):
                await s.execute(update(Item).where(Item.id.in_(chunk)).values(rough_category=None))
                await s.commit()
                wrote += len(chunk)
            # group CONCRETE: rough_category := its category value
            for val, ids in concrete_by_val.items():
                for chunk in _chunks(ids, BATCH):
                    await s.execute(update(Item).where(Item.id.in_(chunk)).values(rough_category=val))
                    await s.commit()
                    wrote += len(chunk)
            print(f"\n!! COMMITTED {wrote} row updates (batched).")

        print(f"\n──────── RESULT ────────")
        print(f"target rows:             {len(rows)}")
        print(f"CONCRETE (rough:=cat):   {counts['CONCRETE']}")
        print(f"NONE     (rough:=None):  {counts['NONE']}")
        print(f"\n--- CONCRETE breakdown (new rough value : count) ---")
        for val, ids in sorted(concrete_by_val.items(), key=lambda x: -len(x[1])):
            print(f"    {val:30s} {len(ids)}")
        print(f"\n=== {mode} complete." + ("" if write else " No data was modified.") + " ===")
        print(f"=== Backup ({len(backup)} rows) at: {backup_path} ===")


if __name__ == "__main__":
    asyncio.run(main())
