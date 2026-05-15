"""
BLS PPI Observations — DB repository layer.

Provides upsert logic for saving normalized BLS PPI data into
the bls_ppi_observations table. Supports both PostgreSQL and SQLite.
"""

import logging
from typing import Any, Dict, List, Set, Tuple

from sqlalchemy import select, func, update, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BLSPPIObservation

logger = logging.getLogger(__name__)

# The 4 columns that form the UNIQUE constraint (uq_bls_ppi_data_point).
UPSERT_KEY_COLUMNS = [
    "source", "dataset_name", "series_id", "date"
]

# Columns to overwrite on conflict.
UPSERT_UPDATE_COLUMNS = [
    "series_name", "year", "period", "period_name", "value",
    "footnotes", "latest", "raw_json",
]


async def upsert_ppi_observations(
    session: AsyncSession,
    rows: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Upsert a list of normalized row dicts into bls_ppi_observations.

    Strategy
    --------
    1. Identify series that have a new 'latest=True' observation in the input.
    2. Reset existing 'latest' flags in the DB for those series.
    3. For each row, query by the 4-column unique key.
       - If exists -> update.
       - If not -> insert.

    Parameters
    ----------
    session : AsyncSession
    rows : list[dict]

    Returns
    -------
    dict  {"inserted": int, "updated": int, "skipped": int}
    """
    inserted = 0
    updated = 0
    skipped = 0

    # 1. Identify series with new 'latest' flag
    series_to_reset: Set[Tuple[str, str, str]] = set()
    for row in rows:
        if row.get("latest"):
            series_to_reset.add((
                row["source"], 
                row["dataset_name"], 
                row["series_id"]
            ))

    # 2. Reset existing latest flags in DB for these series
    for s_src, s_ds, s_id in series_to_reset:
        stmt_reset = (
            update(BLSPPIObservation)
            .where(
                BLSPPIObservation.source == s_src,
                BLSPPIObservation.dataset_name == s_ds,
                BLSPPIObservation.series_id == s_id,
                BLSPPIObservation.latest == True
            )
            .values(latest=False)
        )
        await session.execute(stmt_reset)

    # 3. Standard Upsert
    for row in rows:
        try:
            # Normalize footnotes: [{}] -> []
            footnotes = row.get("footnotes", [])
            if footnotes == [{}]:
                footnotes = []

            # Build the WHERE clause from the unique key columns
            stmt = select(BLSPPIObservation).where(
                BLSPPIObservation.source == row["source"],
                BLSPPIObservation.dataset_name == row["dataset_name"],
                BLSPPIObservation.series_id == row["series_id"],
                BLSPPIObservation.date == row["date"],
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Update mutable fields
                for col in UPSERT_UPDATE_COLUMNS:
                    if col in row:
                        if col == "footnotes":
                            setattr(existing, col, footnotes)
                        else:
                            setattr(existing, col, row[col])
                existing.fetched_at = func.now()
                updated += 1
            else:
                # Insert new row
                new_row = BLSPPIObservation(
                    source=row["source"],
                    dataset_name=row["dataset_name"],
                    series_id=row["series_id"],
                    series_name=row.get("series_name"),
                    year=row["year"],
                    period=row["period"],
                    period_name=row.get("period_name"),
                    date=row["date"],
                    value=row.get("value"),
                    footnotes=footnotes,
                    latest=row.get("latest", False),
                    raw_json=row,  # Store the full normalized dict
                )
                session.add(new_row)
                inserted += 1

        except Exception as e:
            logger.warning(f"Skipped PPI row (series={row.get('series_id')} date={row.get('date')}): {e}")
            skipped += 1

    await session.flush()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


async def count_ppi_rows(session: AsyncSession) -> int:
    """Return the total row count in bls_ppi_observations."""
    result = await session.execute(
        select(func.count()).select_from(BLSPPIObservation)
    )
    return result.scalar_one()


async def get_ppi_series_summary(session: AsyncSession) -> List[Dict[str, Any]]:
    """Return counts and latest status per series_id."""
    stmt = (
        select(
            BLSPPIObservation.series_id,
            func.count(BLSPPIObservation.id).label("total_count"),
            func.sum(cast(BLSPPIObservation.latest, Integer)).label("latest_count")
        )
        .group_by(BLSPPIObservation.series_id)
    )
    result = await session.execute(stmt)
    return [
        {
            "series_id": r.series_id,
            "total_count": r.total_count,
            "latest_count": r.latest_count
        }
        for r in result.all()
    ]
