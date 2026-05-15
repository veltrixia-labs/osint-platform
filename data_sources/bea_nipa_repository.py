"""
BEA NIPA Observations — DB repository layer.

Provides upsert logic for saving normalized BEA NIPA data into
the bea_nipa_observations table. Supports both PostgreSQL and SQLite.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BEANIPAObservation

logger = logging.getLogger(__name__)

# The 5 columns that form the UNIQUE constraint (uq_bea_nipa_data_point).
UPSERT_KEY_COLUMNS = [
    "dataset_name", "table_name", "line_number", "time_period", "frequency"
]

# Columns to overwrite on conflict (everything except the key + id).
UPSERT_UPDATE_COLUMNS = [
    "series_code", "line_description", "metric_name", 
    "cl_unit", "unit_mult", "data_value",
    "note_ref", "statistic", "utc_production_time",
    "raw_json",
]


async def upsert_nipa_observations(
    session: AsyncSession,
    rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Upsert a list of normalized row dicts into bea_nipa_observations.

    Strategy
    --------
    For each row, query by the 5-column unique key.
    - If a matching row exists → update the mutable columns + fetched_at.
    - If no match → insert a new row.

    Parameters
    ----------
    session : AsyncSession
        An active async session (caller is responsible for commit).
    rows : list[dict]
        Normalized row dicts from bea_nipa_normalizer.

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
            stmt = select(BEANIPAObservation).where(
                BEANIPAObservation.dataset_name == row["dataset_name"],
                BEANIPAObservation.table_name == row["table_name"],
                BEANIPAObservation.line_number == row["line_number"],
                BEANIPAObservation.time_period == row["time_period"],
                BEANIPAObservation.frequency == row["frequency"],
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
                new_row = BEANIPAObservation(
                    dataset_name=row["dataset_name"],
                    table_name=row["table_name"],
                    series_code=row.get("series_code"),
                    line_number=row["line_number"],
                    line_description=row.get("line_description"),
                    time_period=row["time_period"],
                    frequency=row["frequency"],
                    metric_name=row.get("metric_name"),
                    cl_unit=row.get("cl_unit"),
                    unit_mult=row.get("unit_mult"),
                    data_value=row.get("data_value"),
                    note_ref=row.get("note_ref"),
                    statistic=row.get("statistic"),
                    utc_production_time=row.get("utc_production_time"),
                    raw_json=row,  # Store the full normalized dict
                )
                session.add(new_row)
                inserted += 1

        except Exception as e:
            logger.warning(f"Skipped NIPA row (table={row.get('table_name')} period={row.get('time_period')}): {e}")
            skipped += 1

    await session.flush()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def count_nipa_rows(session: AsyncSession) -> int:
    """Return the total row count in bea_nipa_observations."""
    result = await session.execute(
        select(func.count()).select_from(BEANIPAObservation)
    )
    return result.scalar_one()
