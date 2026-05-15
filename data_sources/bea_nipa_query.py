"""
BEA NIPA Observations -- Query layer.

Pre-built analytic queries over the bea_nipa_observations table.
All functions accept an AsyncSession and return plain Python dicts/lists.
"""

from typing import Any, Dict, List, Optional
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import BEANIPAObservation


def _to_dict(r: BEANIPAObservation) -> Dict[str, Any]:
    """Helper to convert model to dict."""
    return {
        "table_name": r.table_name,
        "series_code": r.series_code,
        "line_number": r.line_number,
        "line_description": r.line_description,
        "time_period": r.time_period,
        "frequency": r.frequency,
        "metric_name": r.metric_name,
        "cl_unit": r.cl_unit,
        "unit_mult": r.unit_mult,
        "data_value": r.data_value,
        "note_ref": r.note_ref,
    }


async def get_nipa_observation(
    session: AsyncSession,
    table_name: str,
    line_number: str,
    time_period: str,
    frequency: str = "A",
) -> Optional[Dict[str, Any]]:
    """
    Return a single NIPA observation.
    """
    stmt = select(BEANIPAObservation).where(
        BEANIPAObservation.table_name == table_name,
        BEANIPAObservation.line_number == line_number,
        BEANIPAObservation.time_period == time_period,
        BEANIPAObservation.frequency == frequency,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return _to_dict(row) if row else None


async def get_nipa_timeseries(
    session: AsyncSession,
    table_name: str,
    line_number: str,
    frequency: str = "A",
) -> List[Dict[str, Any]]:
    """
    Return the timeseries for a specific table row.
    """
    stmt = (
        select(BEANIPAObservation)
        .where(
            BEANIPAObservation.table_name == table_name,
            BEANIPAObservation.line_number == line_number,
            BEANIPAObservation.frequency == frequency,
            BEANIPAObservation.data_value.isnot(None),
        )
        .order_by(BEANIPAObservation.time_period)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_to_dict(r) for r in rows]


async def get_gdp_current_dollars_timeseries(session: AsyncSession) -> List[Dict[str, Any]]:
    """T10105 Line 1: GDP in current dollars."""
    return await get_nipa_timeseries(session, "T10105", "1")


async def get_gdp_growth_rate_timeseries(session: AsyncSession) -> List[Dict[str, Any]]:
    """T10101 Line 1: GDP percent change."""
    return await get_nipa_timeseries(session, "T10101", "1")


async def get_pce_current_dollars_timeseries(session: AsyncSession) -> List[Dict[str, Any]]:
    """T20305 Line 1: PCE in current dollars."""
    return await get_nipa_timeseries(session, "T20305", "1")


async def get_table_snapshot(
    session: AsyncSession,
    table_name: str,
    time_period: str,
    frequency: str = "A",
) -> List[Dict[str, Any]]:
    """
    Return all rows for a table and time period, sorted by line number.
    """
    # Note: line_number is String, but usually contains integers or sub-indexes like "1.1".
    # Basic string sort works for most cases, but numerical sort is better if possible.
    stmt = (
        select(BEANIPAObservation)
        .where(
            BEANIPAObservation.table_name == table_name,
            BEANIPAObservation.time_period == time_period,
            BEANIPAObservation.frequency == frequency,
        )
        .order_by(BEANIPAObservation.line_number)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_to_dict(r) for r in rows]


async def get_top_lines_by_value(
    session: AsyncSession,
    table_name: str,
    time_period: str,
    top_n: int = 10,
    frequency: str = "A",
) -> List[Dict[str, Any]]:
    """
    Return top-N lines by data_value for a given table and period.
    """
    stmt = (
        select(BEANIPAObservation)
        .where(
            BEANIPAObservation.table_name == table_name,
            BEANIPAObservation.time_period == time_period,
            BEANIPAObservation.frequency == frequency,
            BEANIPAObservation.data_value.isnot(None),
        )
        .order_by(desc(BEANIPAObservation.data_value))
        .limit(top_n)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_to_dict(r) for r in rows]
