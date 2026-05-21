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
from jobs.pro_generation_policy import PRO_FORCE_REALTIME_REBUILD

logger = logging.getLogger(__name__)


async def run_pro_structural_report_generation(
    alert_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    topic: Optional[str] = None,
    report_type: str = "weekly",
    *,
    force_rebuild: bool = PRO_FORCE_REALTIME_REBUILD,
) -> Report:
    """
    Main pipeline for Pro Structural Brief generation.

    Always INSERTs a new Report row (never UPDATE-in-place). When force_rebuild is True
    (default), duplicate/idempotency guards are bypassed upstream.
    """
    analysis_ts = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # 1. Resolve Input — prefer explicit alert, else 24h domain cluster
        alert_log = None
        if alert_id:
            stmt = select(AlertLog).where(AlertLog.id == uuid.UUID(alert_id))
            alert_log = (await db.execute(stmt)).scalar_one_or_none()

        resolved_domain = domain_id or (infer_domain_from_topic(topic) if topic else None)
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

        if isinstance(payload, dict):
            payload["force_rebuild"] = force_rebuild
            payload["analysis_generated_at"] = analysis_ts.isoformat()
            payload["insert_mode"] = "always_insert"

        # 6. Create Report Record (always INSERT — never update existing rows)
        new_report = Report(
            report_type="pro_structural",
            title=f"Structural Impact Brief - {display_name}",
            topic_code=domain_info.get("domain_id", topic or "global"),
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
        
        logger.info(f"Generated Pro Structural Brief: {new_report.id} ({new_report.title})")
        return new_report
