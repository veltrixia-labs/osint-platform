"""
Daily external macro-data sync pipeline (Phase 0).

Runs ExternalDataFetcher steps sequentially with configurable inter-step delay
so API rate limits are respected and the OSINT pipeline stays unblocked.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List

from db.database import AsyncSessionLocal
from jobs.external_data_fetcher import ExternalDataFetcher

logger = logging.getLogger(__name__)

# (step_id, log label, fetcher method name)
EXTERNAL_SYNC_STEPS: List[tuple[str, str, str]] = [
    ("fred", "FRED", "sync_fred"),
    ("bls", "BLS", "sync_bls"),
    ("worldbank", "World Bank", "sync_worldbank"),
    ("comtrade", "UN Comtrade", "sync_comtrade"),
    ("bea", "BEA GDPbyIndustry", "sync_bea_industry_stats"),
    ("census", "Census CBP", "sync_census_cbp"),
]


def _inter_step_delay_seconds() -> float:
    """Pause between sync steps (default 20 minutes)."""
    raw = os.getenv("EXTERNAL_SYNC_INTER_STEP_SECONDS", "1200")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1200.0


def _is_sync_disabled() -> bool:
    return os.getenv("EXTERNAL_DATA_SYNC_DISABLED", "").lower() in (
        "true",
        "1",
        "yes",
    )


async def _run_one_step(step_id: str, label: str, method_name: str) -> Dict[str, Any]:
    """Execute a single fetcher sync inside its own DB session."""
    started = datetime.now(timezone.utc)
    logger.info("[ExternalDataSync] Step start: %s (%s)", step_id, label)
    try:
        async with AsyncSessionLocal() as session:
            fetcher = ExternalDataFetcher(session)
            sync_fn: Callable[..., Awaitable[Dict[str, Any]]] = getattr(fetcher, method_name)
            result = await sync_fn()
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.info(
            "[ExternalDataSync] Step success: %s (%s) in %.1fs — %s",
            step_id,
            label,
            elapsed,
            result,
        )
        return {
            "step": step_id,
            "label": label,
            "status": "success",
            "elapsed_sec": elapsed,
            "result": result,
        }
    except Exception as exc:
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        logger.error(
            "[ExternalDataSync] Step failed: %s (%s) after %.1fs — %s",
            step_id,
            label,
            elapsed,
            exc,
            exc_info=True,
        )
        return {
            "step": step_id,
            "label": label,
            "status": "failed",
            "elapsed_sec": elapsed,
            "error": str(exc),
        }


async def run_daily_external_data_sync_pipeline() -> Dict[str, Any]:
    """
    Run all ExternalDataFetcher sync methods once, sequentially, with jitter between steps.
    Individual step failures are logged; later steps still run (retry next day).
    """
    if _is_sync_disabled():
        logger.info("[ExternalDataSync] Skipped — EXTERNAL_DATA_SYNC_DISABLED is set.")
        return {"status": "skipped", "reason": "disabled"}

    pipeline_started = datetime.now(timezone.utc)
    logger.info("[ExternalDataSync] === Daily macro sync pipeline started (UTC %s) ===", pipeline_started.isoformat())

    step_results: List[Dict[str, Any]] = []
    delay = _inter_step_delay_seconds()

    for index, (step_id, label, method_name) in enumerate(EXTERNAL_SYNC_STEPS):
        step_results.append(await _run_one_step(step_id, label, method_name))
        if index < len(EXTERNAL_SYNC_STEPS) - 1 and delay > 0:
            logger.info(
                "[ExternalDataSync] Inter-step delay %.0fs before next source…",
                delay,
            )
            await asyncio.sleep(delay)

    success_count = sum(1 for r in step_results if r.get("status") == "success")
    failed = [r["step"] for r in step_results if r.get("status") == "failed"]
    finished = datetime.now(timezone.utc)
    summary = {
        "status": "completed",
        "started_at": pipeline_started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - pipeline_started).total_seconds(),
        "steps_total": len(EXTERNAL_SYNC_STEPS),
        "steps_success": success_count,
        "steps_failed": failed,
        "steps": step_results,
    }

    if failed:
        logger.error(
            "[ExternalDataSync] Pipeline finished with failures: %s (%d/%d ok)",
            failed,
            success_count,
            len(EXTERNAL_SYNC_STEPS),
        )
    else:
        logger.info(
            "[ExternalDataSync] Pipeline finished successfully (%d/%d steps).",
            success_count,
            len(EXTERNAL_SYNC_STEPS),
        )

    try:
        from jobs.cleanup_job import update_system_metric

        async with AsyncSessionLocal() as session:
            await update_system_metric(
                session,
                "external_data_sync_last_run",
                finished.isoformat(),
            )
            await update_system_metric(
                session,
                "external_data_sync_last_summary",
                str({"success": success_count, "failed": failed}),
            )
    except Exception as metric_exc:
        logger.warning("[ExternalDataSync] Could not persist system metrics: %s", metric_exc)

    return summary
