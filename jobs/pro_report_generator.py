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
from analysis.pro_structural_context import build_pro_structural_context
from reports.pro_structural_report_builder import build_pro_structural_report, build_pro_structural_report_payload
from reports.text_encoding import sanitize_unicode_tree
from analysis.pro_domain_config import get_pro_domain_config, infer_domain_from_topic

logger = logging.getLogger(__name__)

async def run_pro_structural_report_generation(
    alert_id: Optional[str] = None,
    domain_id: Optional[str] = None,
    topic: Optional[str] = None,
    report_type: str = "weekly"
) -> Report:
    """
    Main pipeline for Pro Structural Brief generation.
    """
    async with AsyncSessionLocal() as db:
        # 1. Resolve Input
        alert_log = None
        if alert_id:
            stmt = select(AlertLog).where(AlertLog.id == uuid.UUID(alert_id))
            alert_log = (await db.execute(stmt)).scalar_one_or_none()
            
        # If no alert_id, but topic/domain provided, try to find latest alert
        if not alert_log:
            search_topic = domain_id or topic
            if search_topic:
                stmt = select(AlertLog).where(AlertLog.topic == search_topic).order_by(desc(AlertLog.triggered_at)).limit(1)
                alert_log = (await db.execute(stmt)).scalar_one_or_none()

        # 2. Build Context
        context = await build_pro_structural_context(
            db, 
            alert_log=alert_log, 
            domain_id=domain_id, 
            topic=topic
        )
        
        # 3. Build Report Markdown & Payload
        report_md = sanitize_unicode_tree(build_pro_structural_report(context))
        payload = build_pro_structural_report_payload(context)
        
        # 4. Prepare Metadata
        domain_info = context.get("domain", {})
        display_name = domain_info.get("display_name", "General Intelligence")
        
        # 5. Create Report Record
        new_report = Report(
            report_type="pro_structural", # Explicitly identify as structural brief
            title=f"Structural Impact Brief - {display_name}",
            topic_code=domain_info.get("domain_id", topic or "global"),
            content_markdown=report_md,
            structured_payload=payload,
            plan_required="pro",
            is_premium=True,
            confidence_level="High",
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(new_report)
        await db.commit()
        await db.refresh(new_report)
        
        logger.info(f"Generated Pro Structural Brief: {new_report.id} ({new_report.title})")
        return new_report
