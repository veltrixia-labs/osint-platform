"""
Pro Structural Report Generator Job.

Orchestrates the generation of Pro-tier structural briefs by aggregating 
analytical context and converting it into a Markdown report.
"""

from typing import Optional, Any
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import Report, AlertLog
from analysis.pro_structural_context import build_pro_structural_context, resolve_latest_domain_alert
from reports.pro_structural_report_builder import build_pro_structural_report, build_pro_structural_report_payload
from reports.text_encoding import sanitize_unicode_tree
from analysis.pro_domain_config import infer_domain_from_topic
from jobs.pro_generation_policy import pro_compile_dedup_enabled
from jobs.pro_structural_dedup import (
    anchor_from_payload,
    compile_anchor_key,
    domain_compile_lock,
    find_structural_brief_in_compile_window,
)

logger = logging.getLogger(__name__)


async def run_pro_structural_report_generation(
    alert_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    topic: Optional[str] = None,
    report_type: str = "weekly",
    *,
    force_rebuild: Optional[bool] = None,
) -> Report:
    """
    Main pipeline for Pro Structural Brief generation.

    When compile dedup is enabled (default), at most one brief per domain per compile window:
    same anchor → skip; new anchor → UPDATE in place; otherwise INSERT.
    """
    if force_rebuild is None:
        force_rebuild = not pro_compile_dedup_enabled()

    analysis_ts = datetime.now(timezone.utc)
    resolved_domain = domain_id or (infer_domain_from_topic(topic) if topic else None) or "global"
    lock = domain_compile_lock(resolved_domain)

    async with lock:
        return await _run_pro_structural_report_generation_locked(
            alert_id=alert_id,
            domain_id=domain_id,
            topic=topic,
            report_type=report_type,
            force_rebuild=force_rebuild,
            analysis_ts=analysis_ts,
            resolved_domain=resolved_domain,
        )


async def _run_pro_structural_report_generation_locked(
    *,
    alert_id: Optional[str],
    domain_id: Optional[str],
    topic: Optional[str],
    report_type: str,
    force_rebuild: bool,
    analysis_ts: datetime,
    resolved_domain: str,
) -> Report:
    async with AsyncSessionLocal() as db:
        # 1. Resolve Input — prefer explicit alert, else 24h domain cluster
        alert_log = None
        if alert_id:
            stmt = select(AlertLog).where(AlertLog.id == uuid.UUID(alert_id))
            alert_log = (await db.execute(stmt)).scalar_one_or_none()

        if not alert_log and resolved_domain:
            alert_log = await resolve_latest_domain_alert(db, resolved_domain)

        if not alert_log and topic:
            stmt = (
                select(AlertLog)
                .where(AlertLog.topic == topic, AlertLog.suppressed == False)  # noqa: E712
                .order_by(desc(AlertLog.triggered_at))
                .limit(1)
            )
            alert_log = (await db.execute(stmt)).scalar_one_or_none()

        # 2. Build Context
        context = await build_pro_structural_context(
            db,
            alert_log=alert_log,
            domain_id=domain_id,
            topic=topic,
            force_rebuild=force_rebuild,
            analysis_generated_at=analysis_ts,
        )
        
        # 3. Build Report Markdown & Payload
        report_md = sanitize_unicode_tree(build_pro_structural_report(context))
        payload = build_pro_structural_report_payload(context)
        
        # 4. Prepare Metadata
        domain_info = context.get("domain", {})
        display_name = domain_info.get("display_name", "General Intelligence")
        
        # 5. Teaser for hub list cards
        exec_summary = (payload.get("executive_summary") or "") if isinstance(payload, dict) else ""
        teaser_md = (exec_summary[:277] + "...") if len(exec_summary) > 280 else exec_summary

        topic_code = domain_info.get("domain_id", topic or resolved_domain or "global")
        signal = context.get("signal") if isinstance(context, dict) else {}
        anchor_alert = None
        if isinstance(signal, dict):
            anchor_alert = signal.get("alert_id")
        anchor_key = compile_anchor_key(topic_code, str(anchor_alert) if anchor_alert else None)

        if isinstance(payload, dict):
            payload["force_rebuild"] = force_rebuild
            payload["analysis_generated_at"] = analysis_ts.isoformat()
            payload["compile_anchor_key"] = anchor_key
            payload["insert_mode"] = "insert"

        use_dedup = pro_compile_dedup_enabled() and not force_rebuild
        if use_dedup:
            existing = await find_structural_brief_in_compile_window(db, topic_code)
            if existing:
                prior_anchor = anchor_from_payload(existing.structured_payload)
                prior_key = compile_anchor_key(topic_code, prior_anchor)
                if prior_key == anchor_key:
                    logger.info(
                        "Skipping duplicate Pro Structural Brief for %s (anchor=%s, window active).",
                        topic_code,
                        anchor_key,
                    )
                    return existing

                existing.title = f"Structural Impact Brief - {display_name}"
                existing.content_markdown = report_md
                existing.structured_payload = payload
                existing.teaser_md = teaser_md or None
                existing.created_at = analysis_ts
                if isinstance(payload, dict):
                    payload["insert_mode"] = "update_in_place"
                existing.structured_payload = payload
                await db.commit()
                await db.refresh(existing)
                logger.info(
                    "Updated Pro Structural Brief in place: %s (%s)",
                    existing.id,
                    topic_code,
                )
                return existing

        if isinstance(payload, dict):
            payload["insert_mode"] = "insert"

        new_report = Report(
            report_type="pro_structural",
            title=f"Structural Impact Brief - {display_name}",
            topic_code=topic_code,
            content_markdown=report_md,
            structured_payload=payload,
            teaser_md=teaser_md or None,
            plan_required="pro",
            is_premium=True,
            confidence_level="High",
            created_at=analysis_ts,
        )

        db.add(new_report)
        await db.commit()
        await db.refresh(new_report)

        logger.info("Generated Pro Structural Brief: %s (%s)", new_report.id, new_report.title)
        return new_report
