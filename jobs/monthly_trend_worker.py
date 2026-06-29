"""
Monthly Trend Flow worker.

Builds and persists one calendar month's flow snapshot into
``monthly_trend_reports``. Idempotent: a month that already has a row is skipped
unless ``force=True``.

Scheduling: ``main_scheduler`` fires this daily but it only runs on day-of-month
== 1, snapshotting the *just-completed* previous month (mirrors the existing
monthly_reports_wrapper pattern).

Run manually / backfill:

    python -m jobs.monthly_trend_worker                 # previous calendar month
    python -m jobs.monthly_trend_worker --year 2026 --month 4
    python -m jobs.monthly_trend_worker --year 2026 --month 4 --force
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import MonthlyTrendReport
from analysis.monthly_trend_builder import build_monthly_trend_snapshot, month_bounds

logger = logging.getLogger(__name__)

# Rolling window: retain the current month + the 2 prior months (3 total).
RETENTION_MONTHS = 3


def _previous_month(now: Optional[datetime] = None) -> tuple[int, int]:
    """(year, month) of the calendar month before ``now`` (UTC)."""
    now = now or datetime.now(timezone.utc)
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


def _oldest_kept_month(now: datetime, keep_months: int = RETENTION_MONTHS) -> tuple[int, int]:
    """(year, month) of the OLDEST month to RETAIN — rows strictly older are pruned.

    Uses absolute 1-based month ordinals (year*12 + month) so year rollovers are
    exact: with keep_months=3, Jan 2026 retains Nov 2025/Dec 2025/Jan 2026 (so the
    cutoff is Nov 2025 and Oct 2025 — "3 months prior to January" — is pruned);
    Aug 2026 retains Jun/Jul/Aug 2026.
    """
    ordinal = now.year * 12 + now.month - (keep_months - 1)
    year = (ordinal - 1) // 12
    month = ordinal - year * 12
    return year, month


async def prune_monthly_trends(
    session: AsyncSession, *, now: Optional[datetime] = None, keep_months: int = RETENTION_MONTHS
) -> int:
    """Delete ``monthly_trend_reports`` older than the rolling window. Returns the
    number of rows removed. Comparison is on the absolute month ordinal so it is
    safe across year boundaries."""
    now = now or datetime.now(timezone.utc)
    year, month = _oldest_kept_month(now, keep_months)
    cutoff_ordinal = year * 12 + month
    result = await session.execute(
        delete(MonthlyTrendReport).where(
            MonthlyTrendReport.period_year * 12 + MonthlyTrendReport.period_month < cutoff_ordinal
        )
    )
    await session.commit()
    pruned = result.rowcount or 0
    logger.info(
        "Monthly trend retention: pruned %d row(s) older than %04d-%02d (keep %d months).",
        pruned, year, month, keep_months,
    )
    return pruned


async def run_monthly_trend_worker(
    session: Optional[AsyncSession] = None,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Build + upsert the snapshot for (year, month). Defaults to previous month."""
    if year is None or month is None:
        year, month = _previous_month()

    owns_session = session is None
    if owns_session:
        session = AsyncSessionLocal()

    try:
        assert session is not None
        existing = (
            await session.execute(
                select(MonthlyTrendReport).where(
                    MonthlyTrendReport.period_year == year,
                    MonthlyTrendReport.period_month == month,
                )
            )
        ).scalar_one_or_none()

        if existing is not None and not force:
            logger.info(
                "Monthly trend for %04d-%02d already exists (id=%s); skipping (use force=True to rebuild).",
                year, month, existing.id,
            )
            return {"status": "skipped_existing", "year": year, "month": month}

        start, end, label = month_bounds(year, month)
        snapshot = await build_monthly_trend_snapshot(session, year, month)
        summary = snapshot["summary"]

        # ── Accumulate signals across rebuilds ───────────────────────────────
        # alert_logs is purged at ALERT_RETENTION_HOURS (~24h), so every rebuild
        # only ever sees the last day of alerts and build_monthly_trend_snapshot()
        # collapses the current month to ~3 days. The per-signal payloads are
        # fully SELF-CONTAINED (the UI renders chart/list/detail straight from
        # them, never re-reading alert_logs), so we UNION the freshly-built
        # signals with those already frozen in the existing row — the snapshot
        # then accumulates a true 30-day trajectory instead of resetting.
        # Forward-only: already-purged days are unrecoverable. Geo-derived fields
        # (node/edge counts, entropy, viscosity, *_payload, alerts_total) still
        # need live AlertLog rows and remain best-effort current-window — a
        # documented limitation. On ANY failure we fall back to the freshly-built
        # summary unchanged (never crash the worker, never lose the live rebuild).
        if existing is not None:
            try:
                prior = (
                    existing.summary_json.get("signals", [])
                    if isinstance(existing.summary_json, dict)
                    else []
                )
                # Key by signal id; freshly-built payloads OVERWRITE prior ones on
                # collision (reflects re-scored importance). Ignore non-dict /
                # id-less entries from either source.
                merged_by_id: Dict[str, Any] = {}
                for sig in prior:
                    if isinstance(sig, dict) and sig.get("id"):
                        merged_by_id[str(sig["id"])] = sig
                for sig in summary.get("signals", []):
                    if isinstance(sig, dict) and sig.get("id"):
                        merged_by_id[str(sig["id"])] = sig

                def _parse_in_window(sig):
                    """Return the tz-aware triggered_at if it falls in [start, end);
                    None if missing, unparseable, or out-of-window."""
                    raw = sig.get("triggered_at")
                    if not isinstance(raw, str):
                        return None
                    try:
                        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    except ValueError:
                        return None
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    return ts if start <= ts < end else None

                dated = []
                for sig in merged_by_id.values():
                    ts = _parse_in_window(sig)
                    if ts is not None:
                        dated.append((ts, sig))
                dated.sort(key=lambda pair: pair[0])  # triggered_at ascending
                merged = [sig for _, sig in dated]

                # Recompute ONLY the signal-derived aggregates from the merged
                # list; geo-derived fields are left exactly as built.
                ids_by_domain: Dict[str, Any] = {}
                for sig in merged:
                    dom = sig.get("domain_id")
                    sid = sig.get("id")
                    if dom and sid:
                        ids_by_domain.setdefault(dom, []).append(str(sid))

                summary["signals"] = merged
                summary["alerts_spiked"] = len(merged)

                domains = summary.get("domains")
                if isinstance(domains, dict):
                    for dom_id, dom_summary in domains.items():
                        if isinstance(dom_summary, dict):
                            ids = ids_by_domain.get(dom_id, [])
                            dom_summary["spiked"] = len(ids)
                            dom_summary["source_alert_ids"] = ids
                    summary["top_sectors"] = [
                        d for d, v in sorted(
                            domains.items(),
                            key=lambda kv: kv[1].get("spiked", 0) if isinstance(kv[1], dict) else 0,
                            reverse=True,
                        )
                        if isinstance(v, dict) and v.get("spiked", 0) > 0
                    ]
            except Exception:
                logger.warning(
                    "Monthly trend signal accumulation failed for %04d-%02d; "
                    "falling back to freshly-built summary.",
                    year, month, exc_info=True,
                )

        if existing is not None:
            existing.period_start = start
            existing.period_end = end
            existing.label = label
            existing.generated_at = datetime.now(timezone.utc)
            existing.schema_version = snapshot["schema_version"]
            existing.nodes_payload = snapshot["nodes"]
            existing.edges_payload = snapshot["edges"]
            existing.summary_json = summary
            existing.alerts_total = int(summary.get("alerts_total", 0))
            existing.alerts_spiked = int(summary.get("alerts_spiked", 0))
            action = "rebuilt"
        else:
            session.add(
                MonthlyTrendReport(
                    id=uuid.uuid4(),
                    period_year=year,
                    period_month=month,
                    period_start=start,
                    period_end=end,
                    label=label,
                    generated_at=datetime.now(timezone.utc),
                    schema_version=snapshot["schema_version"],
                    nodes_payload=snapshot["nodes"],
                    edges_payload=snapshot["edges"],
                    summary_json=summary,
                    alerts_total=int(summary.get("alerts_total", 0)),
                    alerts_spiked=int(summary.get("alerts_spiked", 0)),
                )
            )
            action = "created"

        await session.commit()
        logger.info(
            "Monthly trend %s for %s: alerts=%s spiked=%s nodes=%s edges=%s",
            action, label, summary.get("alerts_total"), summary.get("alerts_spiked"),
            summary.get("node_count"), summary.get("edge_count"),
        )
        return {
            "status": action,
            "year": year,
            "month": month,
            "label": label,
            "summary": summary,
        }
    except Exception:
        if session is not None:
            await session.rollback()
        logger.exception("Monthly trend worker failed for %04d-%02d", year, month)
        raise
    finally:
        if owns_session and session is not None:
            await session.close()


async def _main() -> None:
    p = argparse.ArgumentParser(description="Build a Monthly Trend Flow snapshot")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--month", type=int, default=None)
    p.add_argument("--force", action="store_true", help="Rebuild even if the month already exists")
    args = p.parse_args()
    result = await run_monthly_trend_worker(year=args.year, month=args.month, force=args.force)
    print(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
