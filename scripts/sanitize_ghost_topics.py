"""
Ghost-data sanitizer (DRY-RUN by default).

Re-evaluates recently-ingested Item rows and recently-triggered AlertLog rows
through the NEWLY UNIFIED, boundary-enforced classifier (lightweight_topic:
`infer_topic_from_text(..., title=, strict=True)`) and reports which records the
old naive-substring path mis-stamped (e.g. a ceasefire story filed under
`ai_semiconductor_intelligence` because "ai" bled out of "remain"/"again" and
"intel" out of "intelligence").

READ-ONLY by default: never calls commit() unless `--apply` is passed.

Window = SIGNAL_LOOKBACK_HOURS (default 168h / 7 days) — the active signal
lookback, so we flush ghosts that could still re-seed signals before they age out.

Apply policy (recall-safe, chosen by the architect):
  * RESTAMP  — record moves to a CONCRETE strategic domain (e.g. AI_TECH->CRYPTO).
               Always corrected: zero recall loss. (item.category/rough_category;
               alert.topic.)
  * DROP     — strict re-eval returns None AND `is_non_strategic_noise` fires
               (election / sports / entertainment clutter). Reversible: items have
               category nulled (drops them from signal batches); alerts are
               SUPPRESSED (suppressed=True), never deleted.
  * HOLD     — strict re-eval returns None but it is NOT flagged noise (e.g.
               "Russia Launches Deadly Strikes on Ukraine"): left untouched to
               protect recall.

Usage (repo root; DATABASE_URL / .env — note: prod DB):
  py -3 scripts/sanitize_ghost_topics.py            # dry-run (default)
  py -3 scripts/sanitize_ghost_topics.py --apply    # write (RESTAMP + noise DROP)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Item, AlertLog
from processor.lightweight_topic import infer_topic_from_text, is_non_strategic_noise
from processor.topic_registry import (
    normalize_canonical_topic,
    INTERNAL_TO_STRATEGIC,
)

try:
    from analysis.signal_engine import SIGNAL_LOOKBACK_HOURS
except Exception:
    SIGNAL_LOOKBACK_HOURS = int(os.getenv("SIGNAL_LOOKBACK_HOURS", "168"))

# Action codes
RESTAMP = "RESTAMP"   # concrete -> concrete; corrected, no recall loss
DROP = "DROP"         # -> None AND confirmed non-strategic noise; suppress/null
HOLD = "HOLD"         # -> None but NOT noise; left untouched (protect recall)
KEEP = "KEEP"         # unchanged


def _decide(old: str | None, new: str | None, text: str) -> str:
    """Map an (old, new) topic delta + text to a sanitation action."""
    if (new or None) == (old or None):
        return KEEP
    if new is not None:
        return RESTAMP
    # new is None → drop only if the text is confirmed non-strategic noise.
    return DROP if is_non_strategic_noise(text or "") else HOLD


def _item_text(it: Item) -> str:
    return f"{it.title or ''} {it.summary or ''}".strip()


def _reeval_item(it: Item) -> str | None:
    """Internal-code topic the unified ingest gate would assign now (None = drop)."""
    title = it.title or ""
    return infer_topic_from_text(
        _item_text(it), title=title or None, source_group=it.source_group, strict=True
    )


def _alert_text(a: AlertLog) -> str:
    meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
    return f"{a.target_label or ''} {meta.get('display_title', '')} {meta.get('description', '')}".strip()


def _reeval_alert(a: AlertLog) -> str | None:
    """Strategic UPPER topic the unified classifier would assign now (None = drop).

    Re-derives purely from the alert's own text with NO raw_topic pass-through, so a
    previously mis-stamped topic cannot mask itself."""
    label = a.target_label or ""
    internal = infer_topic_from_text(_alert_text(a), title=label or None, strict=True)
    if internal is None:
        return None
    return INTERNAL_TO_STRATEGIC.get(internal) or normalize_canonical_topic(internal)


def _report(kind: str, scanned: int, rows: list[tuple]) -> None:
    """rows = list of (action, old, new, headline)."""
    by_action: Counter = Counter(r[0] for r in rows if r[0] != KEEP)
    moves: Counter = Counter(f"{r[1] or '<none>'} -> {r[2] or '<DROP:None>'}" for r in rows if r[0] != KEEP)
    print(f"\n──────────────────────── {kind} ────────────────────────")
    print(f"scanned:                {scanned}")
    print(f"RESTAMP (corrected):    {by_action.get(RESTAMP, 0)}")
    print(f"DROP    (noise-conf.):  {by_action.get(DROP, 0)}")
    print(f"HOLD    (review later): {by_action.get(HOLD, 0)}")
    print("top transitions (actionable):")
    for k, v in moves.most_common(12):
        print(f"    {v:5d}  {k}")
    print("samples by action:")
    for act in (RESTAMP, DROP, HOLD):
        shown = [r for r in rows if r[0] == act][:5]
        for _a, old, new, head in shown:
            print(f"  {act:7s} [{(old or '<none>'):28s} -> {(new or '<DROP:None>'):28s}] {head[:52]}")


async def main() -> None:
    p = argparse.ArgumentParser(description="Sanitize mis-stamped (ghost) topics")
    p.add_argument("--apply", action="store_true", help="WRITE changes (RESTAMP + noise DROP)")
    args = p.parse_args()
    write = args.apply

    cutoff = datetime.now(timezone.utc) - timedelta(hours=SIGNAL_LOOKBACK_HOURS)
    mode = "APPLY (WRITES)" if write else "DRY-RUN (read-only)"
    print(f"\n=== Ghost-topic sanitizer - {mode} ===")
    print(f"Window: last {SIGNAL_LOOKBACK_HOURS}h  (created/triggered >= {cutoff.isoformat()})")
    print("Policy: RESTAMP concrete->concrete | DROP only noise-confirmed None | HOLD the rest\n")

    async with AsyncSessionLocal() as s:
        # ── ITEMS ───────────────────────────────────────────────────────────
        items = (await s.execute(select(Item).where(Item.created_at >= cutoff))).scalars().all()
        item_rows: list[tuple] = []
        for it in items:
            old, new = it.category, _reeval_item(it)
            action = _decide(old, new, _item_text(it))
            if action == KEEP:
                continue
            item_rows.append((action, old, new, it.title or ""))
            if write:
                if action == RESTAMP:
                    it.category = new
                    it.rough_category = new
                elif action == DROP:
                    it.category = None          # removes it from topic signal batches
                    it.rough_category = None

        # ── ALERTS ──────────────────────────────────────────────────────────
        alerts = (await s.execute(select(AlertLog).where(AlertLog.triggered_at >= cutoff))).scalars().all()
        alert_rows: list[tuple] = []
        for a in alerts:
            old = normalize_canonical_topic(a.topic) if a.topic else None
            new = _reeval_alert(a)
            action = _decide(old, new, _alert_text(a))
            if action == KEEP:
                continue
            alert_rows.append((action, old, new, a.target_label or ""))
            if write:
                if action == RESTAMP:
                    a.topic = new
                elif action == DROP:
                    a.suppressed = True         # reversible; never deleted

        # READ-ONLY GUARANTEE: only commit on explicit --apply.
        if write:
            await s.commit()
            print("!! COMMITTED writes.")
        else:
            await s.rollback()

        _report("ITEMS", len(items), item_rows)
        _report("ALERTS", len(alerts), alert_rows)

        ai_items = sum(1 for r in item_rows if r[1] == "ai_semiconductor_intelligence" and r[0] == RESTAMP)
        ai_alerts = sum(1 for r in alert_rows if r[1] == "AI_TECH" and r[0] == RESTAMP)
        print(f"\nAI ghost mislabels corrected (RESTAMP off AI): items={ai_items}  alerts={ai_alerts}")
        print(f"\n=== {mode} complete." + ("" if write else " No data was modified.") + " ===")


if __name__ == "__main__":
    asyncio.run(main())
