"""
Monthly Trend Flow API — browse archived monthly flow snapshots.

OPEN / UNGATED by design: per platform UI principles there are no tier locks,
masks, or ghost nodes on this feature. Every archived month is fully readable
and each node/edge carries `source_alert_ids` so the frontend evidence modal
can link straight to the raw AlertLog sources.

Endpoints
─────────
  GET /api/monthly-trends                 → archive index (newest first)
  GET /api/monthly-trends/latest          → newest archived month (full snapshot)
  GET /api/monthly-trends/{year}/{month}  → one month's full snapshot
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from db.database import AsyncSessionLocal
from db.models import MonthlyTrendReport

router = APIRouter(prefix="/monthly-trends", tags=["Monthly Trend Flow"])

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
}


async def _get_db():
    async with AsyncSessionLocal() as session:
        yield session


def _index_item(r: MonthlyTrendReport) -> Dict[str, Any]:
    return {
        "year": r.period_year,
        "month": r.period_month,
        "label": r.label,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "alerts_total": int(r.alerts_total or 0),
        "alerts_spiked": int(r.alerts_spiked or 0),
    }


def _full(r: MonthlyTrendReport) -> Dict[str, Any]:
    return {
        "period": {
            "year": r.period_year,
            "month": r.period_month,
            "label": r.label,
            "start": r.period_start.isoformat() if r.period_start else None,
            "end": r.period_end.isoformat() if r.period_end else None,
        },
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "schema_version": r.schema_version,
        "summary": r.summary_json or {},
        "nodes": r.nodes_payload or [],
        "edges": r.edges_payload or [],
    }


@router.get("")
async def list_monthly_trends(
    response: Response,
    db: AsyncSession = Depends(_get_db),
) -> List[Dict[str, Any]]:
    """Archive index, newest month first (lightweight — no node/edge payloads)."""
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v
    rows = (
        await db.execute(
            select(MonthlyTrendReport).order_by(
                desc(MonthlyTrendReport.period_year),
                desc(MonthlyTrendReport.period_month),
            )
        )
    ).scalars().all()
    return [_index_item(r) for r in rows]


@router.get("/latest")
async def latest_monthly_trend(
    response: Response,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """Newest archived month's full snapshot."""
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v
    row = (
        await db.execute(
            select(MonthlyTrendReport)
            .order_by(
                desc(MonthlyTrendReport.period_year),
                desc(MonthlyTrendReport.period_month),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No monthly trend reports generated yet.")
    return _full(row)


@router.get("/{year}/{month}")
async def get_monthly_trend(
    year: int,
    month: int,
    response: Response,
    db: AsyncSession = Depends(_get_db),
) -> Dict[str, Any]:
    """One month's full flow snapshot (nodes + edges + summary)."""
    for k, v in _NO_STORE_HEADERS.items():
        response.headers[k] = v
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1-12")
    row = (
        await db.execute(
            select(MonthlyTrendReport).where(
                MonthlyTrendReport.period_year == year,
                MonthlyTrendReport.period_month == month,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No trend report for {year}-{month:02d}.")
    return _full(row)
