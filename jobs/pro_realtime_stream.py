"""
Continuous Pro V2 intelligence stream — always INSERT fresh reports per domain cycle.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jobs.pro_brief_regenerator import CORE_PRO_DOMAINS
from jobs.pro_generation_policy import PRO_FORCE_REALTIME_REBUILD
from jobs.pro_report_generator import run_pro_structural_report_generation

logger = logging.getLogger(__name__)


async def run_continuous_pro_intelligence_stream(
    *,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate one fresh Pro Structural brief per domain (INSERT only, no skip/cache).
    """
    targets = domains or CORE_PRO_DOMAINS
    started = datetime.now(timezone.utc)
    generated: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    async def _compile_domain(domain_id: str) -> None:
        report = await run_pro_structural_report_generation(
            domain_id=domain_id,
            force_rebuild=PRO_FORCE_REALTIME_REBUILD,
        )
        payload = report.structured_payload or {}
        generated.append(
            {
                "domain_id": domain_id,
                "report_id": str(report.id),
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "analysis_generated_at": payload.get("analysis_generated_at"),
                "predictive_mode": (payload.get("predictive_forecast") or {}).get("mode"),
                "status": "inserted",
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

    finished = datetime.now(timezone.utc)
    return {
        "status": "ok" if not errors else "partial",
        "force_rebuild": PRO_FORCE_REALTIME_REBUILD,
        "domains": targets,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - started).total_seconds(),
        "inserted_count": len(generated),
        "generated": generated,
        "errors": errors,
    }
