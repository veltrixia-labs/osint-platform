"""
Continuous Pro V2 intelligence stream — always INSERT fresh reports per domain cycle.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jobs.pro_brief_regenerator import CORE_PRO_DOMAINS
from db.database import AsyncSessionLocal
from jobs.pro_generation_policy import pro_compile_dedup_enabled
from jobs.pro_report_generator import run_pro_structural_report_generation
from jobs.pro_structural_dedup import prune_structural_briefs_to_one_per_domain

logger = logging.getLogger(__name__)


async def run_continuous_pro_intelligence_stream(
    *,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compile one Pro Structural brief per domain (deduped per compile window; prunes extras after).
    """
    targets = domains or CORE_PRO_DOMAINS
    started = datetime.now(timezone.utc)
    generated: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    async def _compile_domain(domain_id: str) -> None:
        report = await run_pro_structural_report_generation(
            domain_id=domain_id,
            force_rebuild=False if pro_compile_dedup_enabled() else None,
        )
        payload = report.structured_payload or {}
        generated.append(
            {
                "domain_id": domain_id,
                "report_id": str(report.id),
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "analysis_generated_at": payload.get("analysis_generated_at"),
                "predictive_mode": (payload.get("predictive_forecast") or {}).get("mode"),
                "status": (payload.get("insert_mode") or "inserted"),
            }
        )
        logger.info("Pro realtime stream INSERT domain=%s report_id=%s", domain_id, report.id)

    outcomes = await asyncio.gather(
        *[_compile_domain(domain_id) for domain_id in targets],
        return_exceptions=True,
    )
    for domain_id, outcome in zip(targets, outcomes):
        if isinstance(outcome, Exception):
            logger.exception("Pro realtime stream failed for %s", domain_id)
            errors.append({"domain_id": domain_id, "error": str(outcome)})

    pruned = 0
    if pro_compile_dedup_enabled():
        async with AsyncSessionLocal() as db:
            pruned = await prune_structural_briefs_to_one_per_domain(db)

    finished = datetime.now(timezone.utc)
    return {
        "status": "ok" if not errors else "partial",
        "compile_dedup": pro_compile_dedup_enabled(),
        "pruned_duplicates": pruned,
        "domains": targets,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - started).total_seconds(),
        "inserted_count": len(generated),
        "generated": generated,
        "errors": errors,
    }
