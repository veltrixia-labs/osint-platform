"""
Audit AlertLog and Context Briefs (free_alert) coverage by topic — last N hours.

Usage (repo root, DATABASE_URL or .env):
  py -3 scripts/audit_outputs.py
  py -3 scripts/audit_outputs.py --hours 48
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import AlertLog
from processor.topic_registry import (
    INTERNAL_TO_CANONICAL,
    STRATEGIC_TOPIC_CODES,
    _ALIASES,
    normalize_canonical_topic,
)

SEVERITY_ORDER = ("critical", "elevated", "watch")


def _has_context_brief(meta: Any) -> bool:
    if not isinstance(meta, dict):
        return False
    free_alert = meta.get("free_alert")
    return isinstance(free_alert, dict) and len(free_alert) > 0


def _classify_raw_topic(raw: str | None) -> tuple[str, str]:
    """
    Returns (bucket_for_leak_report, canonical_topic_for_aggregation).
    bucket: OK | NULL_OR_EMPTY | UNCATEGORIZED
    """
    if raw is None or not str(raw).strip():
        return "NULL_OR_EMPTY", "MARKET"

    stripped = str(raw).strip()
    upper = stripped.upper()
    if upper in STRATEGIC_TOPIC_CODES or upper in _ALIASES:
        return "OK", normalize_canonical_topic(stripped)

    lower = stripped.lower()
    if lower in INTERNAL_TO_CANONICAL:
        return "OK", normalize_canonical_topic(stripped)

    return "UNCATEGORIZED", normalize_canonical_topic(stripped)


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells: list[str]) -> str:
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    sep = "  ".join("-" * w for w in widths)
    print(line(headers))
    print(sep)
    for row in rows:
        print(line(row))


async def run_audit(hours: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with AsyncSessionLocal() as db:
        stmt = (
            select(AlertLog)
            .where(AlertLog.triggered_at >= since)
            .order_by(AlertLog.triggered_at.desc())
        )
        alerts = (await db.execute(stmt)).scalars().all()

    total = len(alerts)
    print()
    print(f"=== OSINT Output Audit (last {hours}h, since {_fmt_ts(since)}) ===")
    print(f"Total AlertLog rows: {total}")
    print()

    if total == 0:
        print("No alerts in window. Run scheduler / alert pipeline or widen --hours.")
        return 0

    by_topic: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "alerts": 0,
            "briefs": 0,
            "last_triggered": None,
            "severities": defaultdict(int),
        }
    )
    leak_counts: dict[str, int] = defaultdict(int)
    global_severity: dict[str, int] = defaultdict(int)

    for a in alerts:
        leak_bucket, canon = _classify_raw_topic(a.topic)
        if leak_bucket != "OK":
            leak_counts[leak_bucket] += 1

        bucket = by_topic[canon]
        bucket["alerts"] += 1
        if _has_context_brief(a.metadata_json):
            bucket["briefs"] += 1

        sev = (a.severity or "unknown").lower()
        bucket["severities"][sev] += 1
        global_severity[sev] += 1

        ts = a.triggered_at
        if bucket["last_triggered"] is None or (ts and ts > bucket["last_triggered"]):
            bucket["last_triggered"] = ts

    # Topic table (canonical order + any extras)
    topic_order = sorted(STRATEGIC_TOPIC_CODES) + sorted(
        t for t in by_topic if t not in STRATEGIC_TOPIC_CODES
    )
    rows: list[list[str]] = []
    sum_alerts = 0
    sum_briefs = 0
    for topic in topic_order:
        if topic not in by_topic:
            continue
        b = by_topic[topic]
        n_a = b["alerts"]
        n_b = b["briefs"]
        sum_alerts += n_a
        sum_briefs += n_b
        pct = f"{100.0 * n_b / n_a:.0f}%" if n_a else "-"
        briefs_cell = f"{n_b} ({pct})"
        rows.append(
            [
                topic,
                str(n_a),
                briefs_cell,
                _fmt_ts(b["last_triggered"]),
            ]
        )

    rows.append(
        [
            "TOTAL",
            str(sum_alerts),
            f"{sum_briefs} ({100.0 * sum_briefs / sum_alerts:.0f}%)" if sum_alerts else "0",
            "-",
        ]
    )

    print("--- By topic ---")
    _print_table(["Topic", "Alerts", "Briefs", "Last Triggered"], rows)
    print()

    # Severity
    sev_rows = []
    for sev in SEVERITY_ORDER:
        if global_severity.get(sev):
            sev_rows.append([sev.upper(), str(global_severity[sev])])
    for sev, count in sorted(global_severity.items()):
        if sev not in SEVERITY_ORDER:
            sev_rows.append([sev.upper(), str(count)])

    print("--- Severity (all topics) ---")
    _print_table(["Severity", "Count"], sev_rows)
    print()

    # Per-topic severity (compact)
    print("--- Severity by topic ---")
    for topic in topic_order:
        if topic not in by_topic:
            continue
        parts = []
        for sev in SEVERITY_ORDER:
            c = by_topic[topic]["severities"].get(sev, 0)
            if c:
                parts.append(f"{sev.upper()}={c}")
        if parts:
            print(f"  {topic}: {', '.join(parts)}")
    print()

    # Leaks
    print("--- Topic hygiene ---")
    if not leak_counts:
        print("  OK: no NULL/empty or uncategorized raw topic values in window.")
    else:
        for label, count in sorted(leak_counts.items()):
            print(f"  {label}: {count}")
        print("  (UNCATEGORIZED = raw topic not in strategic map; still aggregated as MARKET)")
    print()

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Audit alerts and Context Briefs by topic")
    p.add_argument("--hours", type=int, default=48, help="Lookback window (default: 48)")
    args = p.parse_args()
    raise SystemExit(asyncio.run(run_audit(args.hours)))


if __name__ == "__main__":
    main()
