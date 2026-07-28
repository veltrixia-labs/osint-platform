"""
BLS PPI Observations — Query layer.

Pre-built analytic queries over the bls_ppi_observations table.
Supports YoY, MoM, and cumulative change calculations.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import BLSPPIObservation

logger = logging.getLogger(__name__)

def _to_dict(r: BLSPPIObservation) -> Dict[str, Any]:
    """Helper to convert model to dict."""
    return {
        "source": r.source,
        "dataset_name": r.dataset_name,
        "series_id": r.series_id,
        "series_name": r.series_name,
        "date": r.date,
        "year": r.year,
        "period": r.period,
        "period_name": r.period_name,
        "value": r.value,
        "latest": r.latest,
    }

def _get_yoy_date(date_str: str) -> str:
    """e.g. 2024-12 -> 2023-12"""
    y, m = date_str.split("-")
    return f"{int(y)-1}-{m}"

def _get_mom_date(date_str: str) -> str:
    """e.g. 2024-12 -> 2024-11, 2024-01 -> 2023-12"""
    y, m = date_str.split("-")
    y_int = int(y)
    m_int = int(m)
    if m_int == 1:
        return f"{y_int-1}-12"
    else:
        return f"{y_int}-{m_int-1:02d}"


async def get_ppi_latest(session: AsyncSession, series_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest observation for a series."""
    stmt = select(BLSPPIObservation).where(
        BLSPPIObservation.series_id == series_id,
        BLSPPIObservation.latest == True
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return _to_dict(row) if row else None


async def get_ppi_timeseries(
    session: AsyncSession, 
    series_id: str, 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return the timeseries for a series, sorted by date."""
    stmt = select(BLSPPIObservation).where(
        BLSPPIObservation.series_id == series_id,
        BLSPPIObservation.value.isnot(None)
    )
    if start_date:
        stmt = stmt.where(BLSPPIObservation.date >= start_date)
    if end_date:
        stmt = stmt.where(BLSPPIObservation.date <= end_date)
    
    stmt = stmt.order_by(BLSPPIObservation.date)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_to_dict(r) for r in rows]


async def get_ppi_change(
    session: AsyncSession, 
    series_id: str, 
    current_date: str, 
    comparison_date: str
) -> Dict[str, Any]:
    """Base helper for calculating change between two dates."""
    # Fetch both rows
    stmt = select(BLSPPIObservation).where(
        BLSPPIObservation.series_id == series_id,
        BLSPPIObservation.date.in_([current_date, comparison_date])
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    
    data = {r.date: r for r in rows}
    curr = data.get(current_date)
    prev = data.get(comparison_date)
    
    res = {
        "series_id": series_id,
        "date": current_date,
        "comparison_date": comparison_date,
        "current_value": curr.value if curr else None,
        "comparison_value": prev.value if prev else None,
        "change_percent": None
    }
    
    # Same class of defect as pro_structural_context._get_macro_observations: the
    # curr operand must be None-checked too (a row can exist with a NULL value).
    # Unreachable today only because bls_ppi_observations is empty; guarded so it
    # cannot fire if that table is ever populated. NULL -> change stays None, never 0.
    if curr and prev and curr.value is not None and prev.value and prev.value != 0:
        res["change_percent"] = round(((curr.value - prev.value) / prev.value) * 100, 2)
        res["series_name"] = curr.series_name
        
    return res


async def get_ppi_yoy_change(session: AsyncSession, series_id: str, date: str) -> Dict[str, Any]:
    """Calculate Year-over-Year change."""
    return await get_ppi_change(session, series_id, date, _get_yoy_date(date))


async def get_ppi_mom_change(session: AsyncSession, series_id: str, date: str) -> Dict[str, Any]:
    """Calculate Month-over-Month change."""
    return await get_ppi_change(session, series_id, date, _get_mom_date(date))


async def get_ppi_period_change(session: AsyncSession, series_id: str, start_date: str, end_date: str) -> Dict[str, Any]:
    """Calculate cumulative change over a period."""
    return await get_ppi_change(session, series_id, end_date, start_date)


async def get_all_latest_ppi(session: AsyncSession) -> List[Dict[str, Any]]:
    """Return latest observations for all series."""
    stmt = select(BLSPPIObservation).where(BLSPPIObservation.latest == True).order_by(BLSPPIObservation.series_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_to_dict(r) for r in rows]


async def get_ppi_pressure_summary(session: AsyncSession, end_date: str = "2024-12") -> List[Dict[str, Any]]:
    """
    Consolidated summary of price pressure across all PPI series.
    Includes Latest, YoY, MoM, and Cumulative (from 2018-01).
    """
    # 1. Get all series IDs present in DB
    stmt_ids = select(BLSPPIObservation.series_id).distinct()
    res_ids = await session.execute(stmt_ids)
    series_ids = [r[0] for r in res_ids.all()]
    
    summary = []
    start_anchor = "2018-01"
    
    for sid in series_ids:
        yoy = await get_ppi_yoy_change(session, sid, end_date)
        mom = await get_ppi_mom_change(session, sid, end_date)
        cum = await get_ppi_period_change(session, sid, start_anchor, end_date)
        
        summary.append({
            "series_id": sid,
            "series_name": yoy.get("series_name") or sid,
            "date": end_date,
            "value": yoy.get("current_value"),
            "yoy_pct": yoy.get("change_percent"),
            "mom_pct": mom.get("change_percent"),
            "cum_pct": cum.get("change_percent"),
        })
        
    # Sort by cumulative change descending
    summary.sort(key=lambda x: (x["cum_pct"] or 0), reverse=True)
    return summary
