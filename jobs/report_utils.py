"""
jobs/report_utils.py
Utility helpers for report maintenance:
  - purge_report_history: hard-delete all report records + filesystem artifacts
  - create_startup_debug_report: diagnostic dummy report (currently disabled)

These are separated from the core generation pipeline to reduce the size of
report_generator.py and make maintenance operations easy to discover.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.models import Report
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def purge_report_history(db: AsyncSession, clear_files: bool = True):
    """
    Completely resets the report history (Hard Cleanup).
    Purges reports, pdf_jobs, and trigger logs from the database,
    and optionally removes filesystem analysis/teaser artifacts.
    """
    from sqlalchemy import delete
    from db.models import PdfJob, ReportTriggerLog, Report

    logger.info("!!! STARTING HARD CLEANUP / REPORT PURGE !!!")

    # 1. Purge DB Records (order matters for FK constraints)
    await db.execute(delete(PdfJob))
    await db.execute(delete(ReportTriggerLog))
    await db.execute(delete(Report))
    await db.commit()
    logger.info("Database report history purged.")

    # 2. Clear Filesystem Artifacts
    if clear_files:
        import glob
        patterns = ["outputs/analysis_*.md", "outputs/teaser_*.md"]
        for p in patterns:
            files = glob.glob(p)
            for f in files:
                try:
                    os.remove(f)
                    logger.info(f"Deleted artifact: {f}")
                except Exception as e:
                    logger.error(f"Failed to delete {f}: {e}")
        logger.info("Filesystem report artifacts cleared.")


async def create_startup_debug_report(db: AsyncSession):
    """Generates a dummy 'System Startup' report to verify DB write capability.

    NOTE: This function is HARD-DISABLED for production stability.
    Re-enable by removing the early return if needed for local debugging.
    """
    # HARD-DISABLED for Production Stability
    return

    logger.info("Generating STARTUP DEBUG DUMMY REPORT...")
    try:
        now = datetime.now(timezone.utc)
        title = f"System Startup Diagnostic: {now.strftime('%Y-%m-%d %H:%M:%S')}"

        stmt = select(Report).where(Report.report_type == "system_diagnostic").order_by(Report.created_at.desc()).limit(1)
        existing = (await db.execute(stmt)).scalars().first()

        if existing and (now - existing.created_at).total_seconds() < 60:
            logger.info("Startup diagnostic report already exists. Skipping.")
            return

        dummy = Report(
            title=title,
            teaser_md="This is a diagnostic report generated automatically at system startup to verify database write capabilities.",
            content_markdown="# Diagnostic Report\n\nDatabase: PostgreSQL (Render)\nStatus: RUNNING",
            report_type="system_diagnostic",
            topic_code="system",
            is_premium=False,
            source_count=0,
            confidence_level="High"
        )
        db.add(dummy)
        await db.commit()
        logger.info("STARTUP DEBUG DUMMY REPORT SAVED SUCCESSFULLY.")
    except Exception as e:
        logger.error(f"FAILED to generate startup debug report: {e}")
