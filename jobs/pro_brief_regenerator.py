"""
Regenerate Pro Structural Briefs for all six strategic domains.

Used by dev/admin endpoints and operational backfills.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from analysis.pro_domain_config import infer_domain_from_topic
from analysis.pro_structural_context import resolve_latest_domain_alert
from jobs.pro_generation_policy import PRO_FORCE_REALTIME_REBUILD
from jobs.pro_report_generator import run_pro_structural_report_generation

logger = logging.getLogger(__name__)

CORE_PRO_DOMAINS = [
    "energy_resource_risk",
    "global_market_intelligence",
    "ai_semiconductor_intelligence",
    "supply_chain_intelligence",
    "crypto_geopolitics",
    "defense_technology",
]


async def audit_pro_structural_reports(db: AsyncSession) -> Dict[str, Any]:
    """Summarize existing pro_structural rows for freshness / schema checks."""
    stmt = (
        select(Report)
        .where(Report.report_type == "pro_structural")
        .order_by(desc(Report.created_at))
        .limit(100)
    )
    rows = (await db.execute(stmt)).scalars().all()
    total = (
        await db.execute(
            select(func.count(Report.id)).where(Report.report_type == "pro_structural")
        )
    ).scalar() or 0

    samples: List[Dict[str, Any]] = []
    for r in rows[:20]:
        payload = r.structured_payload or {}
        samples.append(
            {
                "id": str(r.id),
                "topic_code": r.topic_code,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "has_structured_payload": bool(payload),
                "payload_schema_version": payload.get("payload_schema_version"),
                "has_executive_summary": bool(payload.get("executive_summary")),
                "timeline_events": len(payload.get("event_timeline") or []),
                "macro_cards": len(
                    (payload.get("structural_context") or {}).get("macro_display_cards")
                    or (payload.get("structural_context") or {}).get("macro_observations")
                    or []
                ),
                "content_chars": len(r.content_markdown or ""),
            }
        )

    latest_created = rows[0].created_at.isoformat() if rows and rows[0].created_at else None
    v2_count = sum(
        1
        for r in rows
        if (r.structured_payload or {}).get("payload_schema_version") == "pro_structural_v2"
    )

    return {
        "total_pro_structural": total,
        "latest_created_at": latest_created,
        "sampled_rows": len(rows),
        "v2_in_sample": v2_count,
        "samples": samples,
    }


async def purge_pro_structural_reports(
    db: AsyncSession,
    *,
    domain_ids: Optional[List[str]] = None,
) -> int:
    """Delete existing pro_structural reports (optional domain filter)."""
    stmt = delete(Report).where(Report.report_type == "pro_structural")
    if domain_ids:
        stmt = stmt.where(Report.topic_code.in_(domain_ids))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


async def regenerate_pro_structural_briefs(
    *,
    domains: Optional[List[str]] = None,
    purge_first: bool = False,
    force_rebuild: bool = PRO_FORCE_REALTIME_REBUILD,
) -> Dict[str, Any]:
    """
    Regenerate one fresh brief per domain (always INSERT when force_rebuild=True).
    Purge is optional and off by default in real-time mode.
    """
    target_domains = domains or CORE_PRO_DOMAINS
    generated: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    async with AsyncSessionLocal() as db:
        before_audit = await audit_pro_structural_reports(db)

    purged = 0
    if purge_first:
        async with AsyncSessionLocal() as db:
            purged = await purge_pro_structural_reports(db, domain_ids=target_domains)

    for domain_id in target_domains:
        alert_id: Optional[str] = None
        async with AsyncSessionLocal() as db:
            alert = await resolve_latest_domain_alert(db, domain_id)
            if not alert:
                stmt = (
                    select(AlertLog)
                    .where(AlertLog.suppressed == False)  # noqa: E712
                    .order_by(desc(AlertLog.triggered_at))
                    .limit(80)
                )
                for row in (await db.execute(stmt)).scalars().all():
                    if infer_domain_from_topic(row.topic or "") == domain_id:
                        alert = row
                        break
            alert_id = str(alert.id) if alert else None

        try:
            report = await run_pro_structural_report_generation(
                alert_id=alert_id,
                domain_id=domain_id,
                force_rebuild=force_rebuild,
            )
            payload = report.structured_payload or {}
            generated.append(
                {
                    "domain_id": domain_id,
                    "alert_id": alert_id,
                    "report_id": str(report.id),
                    "title": report.title,
                    "created_at": report.created_at.isoformat() if report.created_at else None,
                    "payload_schema_version": payload.get("payload_schema_version"),
                    "timeline_events": len(payload.get("event_timeline") or []),
                    "macro_cards": len(
                        (payload.get("structural_context") or {}).get("macro_display_cards")
                        or []
                    ),
                }
            )
        except Exception as exc:
            logger.exception("Pro brief regen failed for %s", domain_id)
            errors.append({"domain_id": domain_id, "alert_id": alert_id, "error": str(exc)})

    async with AsyncSessionLocal() as db:
        after_audit = await audit_pro_structural_reports(db)

    return {
        "status": "ok",
        "regenerated_at": datetime.now(timezone.utc).isoformat(),
        "domains": target_domains,
        "purged_count": purged,
        "purge_first": purge_first,
        "force_rebuild": force_rebuild,
        "generated": generated,
        "errors": errors,
        "audit_before": before_audit,
        "audit_after": after_audit,
    }


async def run_pro_platform_rebuild(
    *,
    purge_first: bool = True,
    sync_macro_first: bool = True,
    full_macro_pipeline: bool = False,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Full production refresh: external macro/market sync → purge → regenerate Pro V2 briefs.
    """
    started = datetime.now(timezone.utc)
    macro_sync: Optional[Dict[str, Any]] = None
    if sync_macro_first:
        from jobs.pro_backfill_pipeline import run_sync_external_data

        macro_sync = await run_sync_external_data(
            full_pipeline=full_macro_pipeline,
            include_market=True,
        )

    regen = await regenerate_pro_structural_briefs(
        domains=domains,
        purge_first=purge_first,
    )

    finished = datetime.now(timezone.utc)
    return {
        "status": "ok",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - started).total_seconds(),
        "macro_sync": macro_sync,
        "regeneration": regen,
    }
