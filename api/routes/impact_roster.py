"""
Pro Impact Roster — read-only API over impact_roster_rows.

Serves the scenario impact roster (impact x Merton credit-fragility) that
jobs/load_impact_roster.py loads from the vault's cascade output. Every route is
SELECT-only and gated to the Pro tier, mirroring api/routes/pro_spatial.py.

Two facts the API must never merge or coerce:
  * pd = 0.0   -> the Merton PD was COMPUTED and underflowed below double
                 precision (21 mega-caps do this). It is a real, negligible
                 default probability. Reaches the client as 0.0.
  * pd = null  -> the PD was NOT MEASURABLE (no market cap; SOE/private/segment,
                 or Merton inapplicable). Reaches the client as JSON null.
`combined` (impact x pd) is likewise null when pd is null, and 0.0 when pd is 0.0.

`pd_source_as_of` is deliberately NOT exposed by any route: it is a hand-edited
literal in the upstream PD generator, not a measured date, and must not become a
freshness signal on any surface.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.database import AsyncSessionLocal
from db.models import ImpactRosterLoad, ImpactRosterRow
from api.gating import (
    get_effective_tier,
    TIER_PRO,
    TIER_EXPERTS,
    TIER_ENTERPRISE,
)
from api.auth import get_optional_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pro", tags=["Pro Impact Roster"])

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}

_ALLOWED_TIERS = {TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE}


async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _get_current_tier(
    current_user: Optional[Any] = Depends(get_optional_current_user),
) -> str:
    user = None
    if current_user is not None:
        user = current_user[0] if isinstance(current_user, tuple) else current_user
    return await get_effective_tier(user)


def _require_pro(tier: str, detail: str) -> None:
    if tier not in _ALLOWED_TIERS:
        raise HTTPException(status_code=403, detail=detail)


async def _latest_successful_load(db: AsyncSession) -> Optional[ImpactRosterLoad]:
    """The impact_roster_loads row with the greatest finished_at among successful
    loads. Never returns a 'partial' or 'failed' load."""
    return (
        await db.execute(
            select(ImpactRosterLoad)
            .where(
                ImpactRosterLoad.status == "success",
                ImpactRosterLoad.finished_at.isnot(None),
            )
            .order_by(desc(ImpactRosterLoad.finished_at))
            .limit(1)
        )
    ).scalar_one_or_none()


def _combined(impact: float, pd: Optional[float]) -> Optional[float]:
    """impact x pd, preserving the null/0.0 distinction. null pd -> null combined;
    pd 0.0 -> combined 0.0. Never substitute 0 for a null."""
    return None if pd is None else impact * pd


def _no_store(response: Response) -> None:
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v


@router.get("/impact-roster/scenarios")
async def list_impact_scenarios(
    response: Response,
    db: AsyncSession = Depends(_get_db),
    tier: str = Depends(_get_current_tier),
):
    """Scenarios available for a picker, from the latest successful load only.

    Only scenarios with at least one row appear — a zero-row scenario is absent,
    not reported as a zero-count entry. Does NOT return pd_source_as_of.
    """
    _require_pro(tier, "Pro subscription required for the impact roster.")
    _no_store(response)

    load = await _latest_successful_load(db)
    if load is None:
        raise HTTPException(
            status_code=503,
            detail="No successful impact-roster load is available yet.",
        )

    rows = (
        await db.execute(
            select(ImpactRosterRow.scenario, ImpactRosterRow.entity_kind)
            .where(ImpactRosterRow.load_id == load.id)
        )
    ).all()

    counts: Dict[str, Dict[str, int]] = {}
    for scenario, entity_kind in rows:
        bucket = counts.setdefault(scenario, {"firm": 0, "hub": 0})
        bucket["firm" if entity_kind == "firm" else "hub"] += 1

    scenarios = sorted(
        (
            {
                "scenario": scenario,
                "firm_row_count": c["firm"],
                "hub_row_count": c["hub"],
            }
            for scenario, c in counts.items()  # grouped -> every entry has >= 1 row
        ),
        key=lambda s: s["scenario"],
    )

    return {
        "load": {
            "load_id": str(load.id),
            "finished_at": load.finished_at.isoformat(),
            "rows_written": load.rows_written,
        },
        "scenarios": scenarios,
    }


@router.get("/impact-roster/scenarios/{scenario}")
async def get_impact_scenario(
    scenario: str,
    response: Response,
    db: AsyncSession = Depends(_get_db),
    tier: str = Depends(_get_current_tier),
):
    """The roster for one scenario, from the latest successful load.

    firms sorted by combined (impact x pd) descending, NULLS LAST, then impact
    descending. hubs sorted by impact descending. Unknown/empty scenario -> 404.
    """
    _require_pro(tier, "Pro subscription required for the impact roster.")
    _no_store(response)

    load = await _latest_successful_load(db)
    if load is None:
        raise HTTPException(
            status_code=503,
            detail="No successful impact-roster load is available yet.",
        )

    rows = (
        await db.execute(
            select(ImpactRosterRow)
            .where(
                ImpactRosterRow.load_id == load.id,
                ImpactRosterRow.scenario == scenario,
            )
        )
    ).scalars().all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{scenario}' is not present in the latest impact-roster load.",
        )

    firms = [
        {
            "entity": r.entity,
            "impact": r.impact,
            "pd": r.pd,                      # 0.0 stays 0.0; null stays null
            "pd_category": r.pd_category,
            "pd_reason": r.pd_reason,
            "bucket": r.bucket,
            "combined": _combined(r.impact, r.pd),
        }
        for r in rows
        if r.entity_kind == "firm"
    ]
    firms.sort(
        key=lambda f: (
            f["combined"] is None,                                  # NULLS LAST
            -(f["combined"] if f["combined"] is not None else 0.0),  # combined desc
            -f["impact"],                                           # then impact desc
        )
    )

    hubs = [
        {"entity": r.entity, "impact": r.impact}
        for r in rows
        if r.entity_kind == "region_or_hub"
    ]
    hubs.sort(key=lambda h: -h["impact"])

    return {
        "scenario": scenario,
        "ingested_at": load.finished_at.isoformat(),
        "firms": firms,
        "hubs": hubs,
    }


@router.get("/impact-roster/entities/{entity}")
async def get_impact_entity(
    entity: str,
    response: Response,
    db: AsyncSession = Depends(_get_db),
    tier: str = Depends(_get_current_tier),
):
    """Every scenario in which one entity appears, from the latest successful
    load. PD fields are per-entity (identical across its rows); impact and
    combined are per-scenario. Unknown entity -> 404."""
    _require_pro(tier, "Pro subscription required for the impact roster.")
    _no_store(response)

    load = await _latest_successful_load(db)
    if load is None:
        raise HTTPException(
            status_code=503,
            detail="No successful impact-roster load is available yet.",
        )

    rows = (
        await db.execute(
            select(ImpactRosterRow)
            .where(
                ImpactRosterRow.load_id == load.id,
                ImpactRosterRow.entity == entity,
            )
        )
    ).scalars().all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity}' is not present in the latest impact-roster load.",
        )

    head = rows[0]  # pd/pd_category/pd_reason/bucket/entity_kind are per-entity, constant across rows
    scenarios = [
        {
            "scenario": r.scenario,
            "impact": r.impact,
            "combined": _combined(r.impact, r.pd),
        }
        for r in rows
    ]
    scenarios.sort(
        key=lambda s: (
            s["combined"] is None,
            -(s["combined"] if s["combined"] is not None else 0.0),
            -s["impact"],
        )
    )

    return {
        "entity": head.entity,
        "entity_kind": head.entity_kind,
        "pd": head.pd,                     # 0.0 stays 0.0; null stays null
        "pd_category": head.pd_category,
        "pd_reason": head.pd_reason,
        "bucket": head.bucket,
        "ingested_at": load.finished_at.isoformat(),
        "scenarios": scenarios,
    }
