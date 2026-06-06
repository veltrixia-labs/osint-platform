"""
Ghost-data sanitizer (DRY-RUN by default).

Re-evaluates Item rows and AlertLog rows through the NEWLY UNIFIED, boundary-
enforced classifier (lightweight_topic: `infer_topic_from_text(..., title=,
strict=True)`) and corrects records the old naive-substring path mis-stamped
(e.g. a ceasefire story filed under `ai_semiconductor_intelligence` because "ai"
bled out of "remain"/"again" and "intel" out of "intelligence").

READ-ONLY by default: never writes unless `--apply` is passed.

Scope:
  default        — last SIGNAL_LOOKBACK_HOURS (168h) by created/triggered time.
  --full         — the ENTIRE Item/AlertLog backlog (flush ALL historical ghosts,
                   including ancient rows the signal lookback can still surface).

Apply policy (recall-safe):
  * RESTAMP  — record moves to a CONCRETE strategic domain (e.g. AI_TECH->CRYPTO):
               always corrected, zero recall loss.
  * DROP     — strict re-eval is None AND `is_non_strategic_noise` fires
               (sports/entertainment): items have category nulled (removes them
               from signal batches); alerts are SUPPRESSED (reversible, no delete).
  * HOLD     — strict re-eval None but NOT noise (e.g. "Russia strikes Ukraine"):
               left untouched to protect recall.

Writes use batched bulk UPDATEs (short lock windows). Still: run with the
scheduler PAUSED — confirm the DB is quiet first.

Usage (repo root; DATABASE_URL / .env — prod DB):
  py -3 scripts/sanitize_ghost_topics.py                 # dry-run, 168h
  py -3 scripts/sanitize_ghost_topics.py --full          # dry-run, full backlog
  py -3 scripts/sanitize_ghost_topics.py --full --apply  # WRITE full backlog
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, update
from db.database import AsyncSessionLocal
from db.models import Item, AlertLog
from processor.lightweight_topic import infer_topic_from_text, is_non_strategic_noise
from processor.topic_registry import normalize_canonical_topic, INTERNAL_TO_STRATEGIC

try:
    from analysis.signal_engine import SIGNAL_LOOKBACK_HOURS
except Exception:
    SIGNAL_LOOKBACK_HOURS = int(os.getenv("SIGNAL_LOOKBACK_HOURS", "168"))

BATCH = 500  # rows per bulk UPDATE / commit

RESTAMP, DROP, HOLD, KEEP = "RESTAMP", "DROP", "HOLD", "KEEP"


def _decide(old, new, text: str) -> str:
    if (new or None) == (old or None):
        return KEEP
    if new is not None:
        return RESTAMP
    return DROP if is_non_strategic_noise(text or "") else HOLD


def _item_text(it: Item) -> str:
    return f"{it.title or ''} {it.summary or ''}".strip()


def _reeval_item(it: Item):
    title = it.title or ""
    return infer_topic_from_text(_item_text(it), title=title or None, source_group=it.source_group, strict=True)


def _alert_text(a: AlertLog) -> str:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return f"{a.target_label or ''} {meta.get('display_title', '')} {meta.get('description', '')}".strip()


def _reeval_alert(a: AlertLog):
    label = a.target_label or ""
    internal = infer_topic_from_text(_alert_text(a), title=label or None, strict=True)
    if internal is None:
        return None
    return INTERNAL_TO_STRATEGIC.get(internal) or normalize_canonical_topic(internal)


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _report(kind: str, scanned: int, rows: list[tuple]) -> None:
    by_action: Counter = Counter(r[0] for r in rows)
    moves: Counter = Counter(f"{r[1] or '<none>'} -> {r[2] or '<DROP:None>'}" for r in rows)
    print(f"\n──────────────────────── {kind} ────────────────────────")
    print(f"scanned:                {scanned}")
    print(f"RESTAMP (corrected):    {by_action.get(RESTAMP, 0)}")
    print(f"DROP    (noise-conf.):  {by_action.get(DROP, 0)}")
    print(f"HOLD    (review later): {by_action.get(HOLD, 0)}")
    print("top transitions (actionable):")
    for k, v in moves.most_common(12):
        print(f"    {v:6d}  {k}")
    for act in (RESTAMP, DROP):
        shown = [r for r in rows if r[0] == act][:5]
        for _a, old, new, head in shown:
            print(f"  {act:7s} [{(old or '<none>'):28s} -> {(new or '<DROP:None>'):28s}] {head[:50]}")


async def main() -> None:
    p = argparse.ArgumentParser(description="Sanitize mis-stamped (ghost) topics")
    p.add_argument("--apply", action="store_true", help="WRITE changes (batched bulk UPDATE)")
    p.add_argument("--full", action="store_true", help="Process the ENTIRE backlog (ignore the 168h window)")
    args = p.parse_args()
    write, full = args.apply, args.full

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=SIGNAL_LOOKBACK_HOURS)
    mode = "APPLY (WRITES)" if write else "DRY-RUN (read-only)"
    scope = "FULL BACKLOG" if full else f"last {SIGNAL_LOOKBACK_HOURS}h"
    print(f"\n=== Ghost-topic sanitizer - {mode} - scope: {scope} ===")
    print("Policy: RESTAMP concrete->concrete | DROP only noise-confirmed None | HOLD the rest\n")

    async with AsyncSessionLocal() as s:
        # ── READ PHASE (stream; read-only) ──────────────────────────────────
        item_rows: list[tuple] = []
        item_restamp: dict[str, list] = defaultdict(list)
        item_drop: list = []
        item_scanned = 0
        istmt = select(Item)
        if not full:
            istmt = istmt.where(Item.created_at >= cutoff)
        async for it in await s.stream_scalars(istmt.execution_options(yield_per=1000)):
            item_scanned += 1
            old, new = it.category, _reeval_item(it)
            act = _decide(old, new, _item_text(it))
            if act == KEEP:
                continue
            item_rows.append((act, old, new, it.title or ""))
            if act == RESTAMP:
                item_restamp[new].append(it.id)
            elif act == DROP:
                item_drop.append(it.id)

        alert_rows: list[tuple] = []
        alert_restamp: dict[str, list] = defaultdict(list)
        alert_suppress: list = []
        alert_scanned = 0
        astmt = select(AlertLog)
        if not full:
            astmt = astmt.where(AlertLog.triggered_at >= cutoff)
        async for a in await s.stream_scalars(astmt.execution_options(yield_per=1000)):
            alert_scanned += 1
            old = normalize_canonical_topic(a.topic) if a.topic else None
            new = _reeval_alert(a)
            act = _decide(old, new, _alert_text(a))
            if act == KEEP:
                continue
            alert_rows.append((act, old, new, a.target_label or ""))
            if act == RESTAMP:
                alert_restamp[new].append(a.id)
            elif act == DROP:
                alert_suppress.append(a.id)

        # ── WRITE PHASE (only --apply; batched bulk UPDATE) ─────────────────
        if write:
            wrote = 0
            for new_cat, ids in item_restamp.items():
                for chunk in _chunks(ids, BATCH):
                    await s.execute(update(Item).where(Item.id.in_(chunk)).values(category=new_cat, rough_category=new_cat))
                    await s.commit()
                    wrote += len(chunk)
            for chunk in _chunks(item_drop, BATCH):
                await s.execute(update(Item).where(Item.id.in_(chunk)).values(category=None, rough_category=None))
                await s.commit()
                wrote += len(chunk)
            for new_topic, ids in alert_restamp.items():
                for chunk in _chunks(ids, BATCH):
                    await s.execute(update(AlertLog).where(AlertLog.id.in_(chunk)).values(topic=new_topic))
                    await s.commit()
                    wrote += len(chunk)
            for chunk in _chunks(alert_suppress, BATCH):
                await s.execute(update(AlertLog).where(AlertLog.id.in_(chunk)).values(suppressed=True))
                await s.commit()
                wrote += len(chunk)
            print(f"!! COMMITTED {wrote} row updates (batched).")

        # ── REPORT ──────────────────────────────────────────────────────────
        _report("ITEMS", item_scanned, item_rows)
        _report("ALERTS", alert_scanned, alert_rows)
        ai_items = sum(1 for r in item_rows if r[1] == "ai_semiconductor_intelligence" and r[0] == RESTAMP)
        ai_alerts = sum(1 for r in alert_rows if r[1] == "AI_TECH" and r[0] == RESTAMP)
        print(f"\nAI ghost mislabels corrected (RESTAMP off AI): items={ai_items}  alerts={ai_alerts}")
        print(f"\n=== {mode} complete." + ("" if write else " No data was modified.") + " ===")


if __name__ == "__main__":
    asyncio.run(main())
