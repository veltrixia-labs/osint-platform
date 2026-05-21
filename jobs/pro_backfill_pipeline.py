"""
Unified Pro production backfill: external data sync → purge → Pro V2 brief regeneration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.pro_global_series import ENERGY_GEOPOLITICAL_SERIES_IDS
from db.database import AsyncSessionLocal
from db.models import ExternalDataSeries, ExternalObservation, MarketDataPrice
from jobs.external_data_sync import (
    run_daily_external_data_sync_pipeline,
    run_pro_macro_data_sync,
)

logger = logging.getLogger(__name__)

PRIORITY_SERIES_IDS = list(
    dict.fromkeys(
        [
            *ENERGY_GEOPOLITICAL_SERIES_IDS,
            "CPIAUCSL",
            "FEDFUNDS",
            "DGS10",
            "WPU05",
            "2709",
            "2711",
        ]
    )
)


async def audit_external_data_coverage(db: AsyncSession) -> Dict[str, Any]:
    """Verify key macro series exist in external_observations (latest rows)."""
    series_rows: Dict[str, Any] = {}
    for sid in PRIORITY_SERIES_IDS:
        latest_stmt = (
            select(ExternalObservation)
            .where(
                ExternalObservation.series_id == sid,
                ExternalObservation.is_latest == True,  # noqa: E712
            )
            .limit(1)
        )
        obs = (await db.execute(latest_stmt)).scalar_one_or_none()
        count_stmt = select(func.count(ExternalObservation.id)).where(
            ExternalObservation.series_id == sid
        )
        total = (await db.execute(count_stmt)).scalar() or 0
        series_rows[sid] = {
            "observation_rows": total,
            "has_latest": obs is not None,
            "latest_value": obs.value if obs else None,
            "latest_date": obs.date.isoformat() if obs and obs.date else None,
            "source": obs.source if obs else None,
        }

    series_total = (
        await db.execute(select(func.count(ExternalDataSeries.id)))
    ).scalar() or 0
    obs_total = (
        await db.execute(select(func.count(ExternalObservation.id)))
    ).scalar() or 0
    market_prices = (
        await db.execute(select(func.count(MarketDataPrice.id)))
    ).scalar() or 0

    energy_ready = all(
        series_rows.get(sid, {}).get("has_latest")
        for sid in ("DCOILWTICO", "WCESTUS1")
        if sid in series_rows
    )
    gpr_ready = any(
        series_rows.get(sid, {}).get("has_latest")
        for sid in ("GPRH", "GPRHT", "GPRA")
        if sid in series_rows
    )

    return {
        "external_data_series_count": series_total,
        "external_observations_count": obs_total,
        "market_data_prices_count": market_prices,
        "energy_core_ready": energy_ready,
        "gpr_any_ready": gpr_ready,
        "priority_series": series_rows,
    }


async def run_sync_external_data(
    *,
    full_pipeline: bool = False,
    include_market: bool = True,
) -> Dict[str, Any]:
    """
    Backfill external_observations + market prices.

    - full_pipeline=False: Pro-priority sources (FRED/BLS/BEA/EIA/OPEC/Comtrade/…)
    - full_pipeline=True: complete daily EXTERNAL_SYNC_STEPS (+ market if include_market)
    """
    if full_pipeline:
        macro_result = await run_daily_external_data_sync_pipeline()
        market_result: Dict[str, Any] = {"status": "skipped"}
        if include_market:
            market_result = await run_pro_macro_data_sync(
                full_pipeline=False,
                skip_inter_step_delay=True,
                sync_market_data=True,
            )
            market_result = market_result.get("market_data", market_result)
        sync_payload = {"mode": "full_daily", "macro_pipeline": macro_result, "market_data": market_result}
    else:
        sync_payload = await run_pro_macro_data_sync(
            full_pipeline=False,
            skip_inter_step_delay=True,
            sync_market_data=include_market,
        )

    async with AsyncSessionLocal() as db:
        coverage = await audit_external_data_coverage(db)

    return {
        "status": sync_payload.get("status", "completed"),
        "sync": sync_payload,
        "coverage_after_sync": coverage,
    }


async def run_backfill_and_rebuild(
    *,
    purge_first: bool = True,
    full_sync: bool = False,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    One-shot: sync external data → audit → purge pro_structural → regenerate V2 briefs.
    """
    started = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        coverage_before = await audit_external_data_coverage(db)

    sync_result = await run_sync_external_data(
        full_pipeline=full_sync,
        include_market=True,
    )

    from jobs.pro_brief_regenerator import regenerate_pro_structural_briefs

    regen_result = await regenerate_pro_structural_briefs(
        domains=domains,
        purge_first=purge_first,
    )

    finished = datetime.now(timezone.utc)
    return {
        "status": "ok",
        "pipeline": "backfill_and_rebuild",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_sec": (finished - started).total_seconds(),
        "coverage_before_sync": coverage_before,
        "sync": sync_result,
        "regeneration": regen_result,
        "coverage_after_sync": sync_result.get("coverage_after_sync"),
    }
