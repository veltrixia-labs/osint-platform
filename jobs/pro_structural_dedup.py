"""
Pro Structural Brief deduplication — one active card per domain per compile window.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Report
from jobs.pro_structural_reports import pro_structural_report_filters

logger = logging.getLogger(__name__)

_domain_locks: Dict[str, asyncio.Lock] = {}


def pro_compile_dedup_enabled() -> bool:
    return os.getenv("PRO_COMPILE_DEDUP", "true").lower() in ("true", "1", "yes")


def pro_compile_dedup_window_minutes() -> int:
    return max(1, int(os.getenv("PRO_COMPILE_DEDUP_WINDOW_MINUTES", "30")))


def domain_compile_lock(domain_id: str) -> asyncio.Lock:
    if domain_id not in _domain_locks:
        _domain_locks[domain_id] = asyncio.Lock()
    return _domain_locks[domain_id]


def compile_anchor_key(domain_id: str, alert_id: Optional[str]) -> str:
    return f"{domain_id}:{alert_id or 'macro'}"


def anchor_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    signal = payload.get("signal") or {}
    if isinstance(signal, dict):
        aid = signal.get("alert_id")
        if aid:
            return str(aid)
    return None


async def find_latest_structural_brief_for_domain(
    db: AsyncSession,
    domain_id: str,
) -> Optional[Report]:
    stmt = (
        select(Report)
        .where(*pro_structural_report_filters(), Report.topic_code == domain_id)
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def find_structural_brief_in_compile_window(
    db: AsyncSession,
    domain_id: str,
) -> Optional[Report]:
    window = timedelta(minutes=pro_compile_dedup_window_minutes())
    threshold = datetime.now(timezone.utc) - window
    stmt = (
        select(Report)
        .where(
            *pro_structural_report_filters(),
            Report.topic_code == domain_id,
            Report.created_at >= threshold,
        )
        .order_by(desc(Report.created_at))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def prune_structural_briefs_to_one_per_domain(db: AsyncSession) -> int:
    """
    Keep only the newest structural brief per topic_code; delete older duplicates.
    """
    stmt = (
        select(Report)
        .where(*pro_structural_report_filters())
        .order_by(desc(Report.created_at))
    )
    rows = (await db.execute(stmt)).scalars().all()
    seen_topics: set[str] = set()
    delete_ids: list = []

    for row in rows:
        topic = (row.topic_code or "global").strip() or "global"
        if topic in seen_topics:
            delete_ids.append(row.id)
        else:
            seen_topics.add(topic)

    if not delete_ids:
        return 0

    result = await db.execute(delete(Report).where(Report.id.in_(delete_ids)))
    await db.commit()
    deleted = int(result.rowcount or 0)
    logger.info("Pruned %s duplicate pro_structural brief(s) (one per domain retained).", deleted)
    return deleted


def latest_reports_per_topic(reports: list[Report]) -> list[Report]:
    """API-safe: newest row per topic_code."""
    by_topic: Dict[str, Report] = {}
    for report in sorted(reports, key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        topic = (report.topic_code or "global").strip() or "global"
        if topic not in by_topic:
            by_topic[topic] = report
    return sorted(
        by_topic.values(),
        key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
