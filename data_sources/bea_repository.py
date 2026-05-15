"""
BEA GDP by Industry — DB repository layer.

Provides upsert logic for saving normalized BEA data into
the bea_gdp_by_industry table.  Supports both PostgreSQL and SQLite.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BEAGDPByIndustry

logger = logging.getLogger(__name__)

# The 6 columns that form the UNIQUE constraint (uq_bea_gdp_data_point).
UPSERT_KEY_COLUMNS = [
    "dataset_name", "table_id", "frequency",
    "year", "quarter", "industry",
]

# Columns to overwrite on conflict (everything except the key + id).
UPSERT_UPDATE_COLUMNS = [
    "industry_description", "data_value",
    "note_ref", "note_text",
    "statistic", "utc_production_time",
    "raw_json",
]


async def upsert_gdp_rows(
    session: AsyncSession,
    rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Upsert a list of normalized row dicts into bea_gdp_by_industry.

    Strategy
    --------
    For each row, query by the 6-column unique key.
    - If a matching row exists → update the mutable columns + fetched_at.
    - If no match → insert a new row.

    This approach works identically on PostgreSQL and SQLite without
    requiring dialect-specific INSERT ... ON CONFLICT syntax.

    Parameters
    ----------
    session : AsyncSession
        An active async session (caller is responsible for commit).
    rows : list[dict]
        Normalized row dicts from bea_normalizer.

    Returns
    -------
    dict  {"inserted": int, "updated": int, "skipped": int}
    """
    inserted = 0
    updated = 0
    skipped = 0

    for row in rows:
        try:
            # Build the WHERE clause from the unique key columns
            stmt = select(BEAGDPByIndustry).where(
                BEAGDPByIndustry.dataset_name == row["dataset_name"],
                BEAGDPByIndustry.table_id == row["table_id"],
                BEAGDPByIndustry.frequency == row["frequency"],
                BEAGDPByIndustry.year == row["year"],
                BEAGDPByIndustry.quarter == row["quarter"],
                BEAGDPByIndustry.industry == row["industry"],
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update mutable fields
                for col in UPSERT_UPDATE_COLUMNS:
                    if col in row:
                        setattr(existing, col, row[col])
                existing.fetched_at = func.now()
                updated += 1
            else:
                # Insert new row
                new_row = BEAGDPByIndustry(
                    dataset_name=row["dataset_name"],
                    table_id=row["table_id"],
                    frequency=row["frequency"],
                    year=row["year"],
                    quarter=row["quarter"],
                    industry=row["industry"],
                    industry_description=row.get("industry_description"),
                    data_value=row.get("data_value"),
                    note_ref=row.get("note_ref"),
                    note_text=row.get("note_text"),
                    statistic=row.get("statistic"),
                    utc_production_time=row.get("utc_production_time"),
                    raw_json=row,  # Store the full normalized dict as audit trail
                )
                session.add(new_row)
                inserted += 1

        except Exception as e:
            logger.warning(f"Skipped row (industry={row.get('industry')}): {e}")
            skipped += 1

    await session.flush()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def count_gdp_rows(session: AsyncSession) -> int:
    """Return the total row count in bea_gdp_by_industry."""
    result = await session.execute(
        select(func.count()).select_from(BEAGDPByIndustry)
    )
    return result.scalar_one()
