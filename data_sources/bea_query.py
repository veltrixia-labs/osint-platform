"""
BEA GDP by Industry -- Query layer.

Pre-built analytic queries over the bea_gdp_by_industry table.
All functions accept an AsyncSession and return plain Python dicts/lists.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BEAGDPByIndustry
from data_sources.bea_industry_classifier import (
    TOTAL_CODES,
    AGGREGATE_CODES,
    SECTOR_CODES,
    classify_industry_code,
)

# All codes that are NOT leaf-level industries (used for legacy exclude_aggregates).
AGGREGATE_INDUSTRY_CODES = TOTAL_CODES | AGGREGATE_CODES


async def get_total_gdp_by_year(
    session: AsyncSession,
    year: str,
    table_id: str = "1",
    frequency: str = "A",
) -> Optional[Dict[str, Any]]:
    """
    Return the GDP total row for a given year.

    Returns
    -------
    dict | None
        {"year": "2022", "data_value": 26054.6, "industry_description": "Gross domestic product"}
    """
    stmt = (
        select(BEAGDPByIndustry)
        .where(
            BEAGDPByIndustry.industry == "GDP",
            BEAGDPByIndustry.year == year,
            BEAGDPByIndustry.table_id == table_id,
            BEAGDPByIndustry.frequency == frequency,
            BEAGDPByIndustry.data_value.isnot(None),
        )
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if not row:
        return None

    return {
        "year": row.year,
        "data_value": row.data_value,
        "industry_description": row.industry_description,
        "statistic": row.statistic,
        "note_text": row.note_text,
    }


async def get_top_industries_by_year(
    session: AsyncSession,
    year: str,
    top_n: int = 10,
    table_id: str = "1",
    frequency: str = "A",
    exclude_aggregates: bool = True,
    sector_only: bool = False,
) -> List[Dict[str, Any]]:
    """
    Return the top-N industries by data_value for a given year.

    Parameters
    ----------
    exclude_aggregates : bool
        If True, exclude total/aggregate rows (default behaviour).
    sector_only : bool
        If True, return ONLY sector-level codes (no subsectors/details).
        Overrides exclude_aggregates.

    Returns
    -------
    list[dict]
        [{"rank": 1, "industry": "53", ..., "level": "sector"}, ...]
    """
    stmt = (
        select(BEAGDPByIndustry)
        .where(
            BEAGDPByIndustry.year == year,
            BEAGDPByIndustry.table_id == table_id,
            BEAGDPByIndustry.frequency == frequency,
            BEAGDPByIndustry.data_value.isnot(None),
        )
        .order_by(desc(BEAGDPByIndustry.data_value))
    )

    if sector_only:
        stmt = stmt.where(BEAGDPByIndustry.industry.in_(SECTOR_CODES))
    elif exclude_aggregates:
        stmt = stmt.where(
            BEAGDPByIndustry.industry.notin_(AGGREGATE_INDUSTRY_CODES)
        )

    stmt = stmt.limit(top_n)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "rank": i + 1,
            "industry": r.industry,
            "industry_description": r.industry_description,
            "data_value": r.data_value,
            "level": classify_industry_code(r.industry),
        }
        for i, r in enumerate(rows)
    ]


async def get_industry_timeseries(
    session: AsyncSession,
    industry_code: str,
    table_id: str = "1",
    frequency: str = "A",
) -> List[Dict[str, Any]]:
    """
    Return the data_value for a given industry across all available years.

    Returns
    -------
    list[dict]
        [{"year": "2020", "data_value": 2345.6}, {"year": "2021", ...}, ...]
    """
    stmt = (
        select(BEAGDPByIndustry)
        .where(
            BEAGDPByIndustry.industry == industry_code,
            BEAGDPByIndustry.table_id == table_id,
            BEAGDPByIndustry.frequency == frequency,
            BEAGDPByIndustry.data_value.isnot(None),
        )
        .order_by(BEAGDPByIndustry.year)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "year": r.year,
            "data_value": r.data_value,
            "industry_description": r.industry_description,
        }
        for r in rows
    ]


async def get_sector_share(
    session: AsyncSession,
    year: str,
    table_id: str = "1",
    frequency: str = "A",
    sector_only: bool = False,
) -> List[Dict[str, Any]]:
    """
    Calculate each industry's share of total GDP (%).

    Parameters
    ----------
    sector_only : bool
        If True, include only sector-level codes so shares sum to ~100%.

    Returns
    -------
    list[dict]  sorted by share descending
        [{"industry": "53", ..., "share_pct": 13.33, "level": "sector"}, ...]
    """
    # 1. Get total GDP
    gdp = await get_total_gdp_by_year(session, year, table_id, frequency)
    if not gdp or not gdp["data_value"]:
        return []

    gdp_total = gdp["data_value"]

    # 2. Build query
    stmt = (
        select(BEAGDPByIndustry)
        .where(
            BEAGDPByIndustry.year == year,
            BEAGDPByIndustry.table_id == table_id,
            BEAGDPByIndustry.frequency == frequency,
            BEAGDPByIndustry.data_value.isnot(None),
        )
        .order_by(desc(BEAGDPByIndustry.data_value))
    )

    if sector_only:
        stmt = stmt.where(BEAGDPByIndustry.industry.in_(SECTOR_CODES))
    else:
        stmt = stmt.where(
            BEAGDPByIndustry.industry.notin_(AGGREGATE_INDUSTRY_CODES)
        )

    result = await session.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "industry": r.industry,
            "industry_description": r.industry_description,
            "data_value": r.data_value,
            "gdp_total": gdp_total,
            "share_pct": round((r.data_value / gdp_total) * 100, 2),
            "level": classify_industry_code(r.industry),
        }
        for r in rows
    ]
