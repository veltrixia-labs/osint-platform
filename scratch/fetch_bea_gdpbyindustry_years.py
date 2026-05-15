"""
Fetch BEA GDPbyIndustry for multiple years.

Pipeline: API fetch -> raw JSON save -> normalize -> normalized JSON save -> DB upsert.

Usage:
    .venv\\Scripts\\python.exe scratch/fetch_bea_gdpbyindustry_years.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from data_sources.bea_client import BEAClient
from data_sources.bea_normalizer import normalize_gdp_by_industry
from data_sources.bea_repository import upsert_gdp_rows, count_gdp_rows
from db.database import AsyncSessionLocal

# ── Configuration ─────────────────────────────────────────────────────

YEARS = ["2018", "2019", "2020", "2021", "2022", "2023", "2024"]
DATASET = "GDPbyIndustry"
TABLE_ID = "1"
INDUSTRY = "ALL"
FREQUENCY = "A"

# Seconds to wait between API calls to be polite to BEA servers.
API_DELAY = 1.0


def fetch_and_save(client: BEAClient, year: str, scratch_dir: Path):
    """Fetch one year, save raw + normalized JSON. Return normalized rows."""

    # ── 1. Fetch from API ─────────────────────────────────────────
    print(f"\n  [{year}] Fetching from BEA API...")
    raw_json = client.get_data(
        dataset_name=DATASET,
        TableID=TABLE_ID,
        Industry=INDUSTRY,
        Year=year,
        Frequency=FREQUENCY,
    )

    # ── 2. Save raw JSON ──────────────────────────────────────────
    raw_file = scratch_dir / f"bea_gdpbyindustry_table1_{year}_a.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(raw_json, f, indent=2)
    print(f"  [{year}] Raw JSON saved: {raw_file.name}")

    # ── 3. Normalize ──────────────────────────────────────────────
    rows = normalize_gdp_by_industry(raw_json)
    print(f"  [{year}] Normalized: {len(rows)} rows")

    # ── 4. Save normalized JSON ───────────────────────────────────
    norm_file = scratch_dir / f"bea_gdpbyindustry_table1_{year}_a_normalized.json"
    with open(norm_file, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"  [{year}] Normalized JSON saved: {norm_file.name}")

    return rows


async def upsert_to_db(all_rows):
    """Upsert all normalized rows into DB."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await upsert_gdp_rows(session, all_rows)
    return result


async def get_total_count():
    """Get total row count from DB."""
    async with AsyncSessionLocal() as session:
        return await count_gdp_rows(session)


async def run_timeseries_check():
    """Run get_industry_timeseries for 31G and sector_only ranking for 2024."""
    from data_sources.bea_query import get_industry_timeseries, get_top_industries_by_year

    async with AsyncSessionLocal() as session:
        # Timeseries for Manufacturing
        print("\n" + "=" * 60)
        print("Manufacturing (31G) Timeseries")
        print("=" * 60)
        ts = await get_industry_timeseries(session, "31G")
        for point in ts:
            print(f"  {point['year']}: ${point['data_value']:>10,.1f}B")

        # 2024 sector_only ranking
        print("\n" + "=" * 60)
        print("2024 Sector Ranking (sector_only=True)")
        print("=" * 60)
        top = await get_top_industries_by_year(
            session, "2024", top_n=10, sector_only=True
        )
        for row in top:
            print(f"  #{row['rank']:>2}  {row['industry']:>6s}  "
                  f"${row['data_value']:>10,.1f}B  {row['industry_description']}")


def main():
    # ── Init ──────────────────────────────────────────────────────
    try:
        client = BEAClient()
    except ValueError as e:
        print(f"Error: {e}")
        return

    scratch_dir = Path(__file__).parent

    # ── Fetch all years ───────────────────────────────────────────
    print("=" * 60)
    print(f"Fetching BEA {DATASET} Table {TABLE_ID} for years: {', '.join(YEARS)}")
    print("=" * 60)

    all_rows = []
    year_counts = {}

    for i, year in enumerate(YEARS):
        rows = fetch_and_save(client, year, scratch_dir)
        year_counts[year] = len(rows)
        all_rows.extend(rows)

        # Rate limit (skip delay after last request)
        if i < len(YEARS) - 1:
            time.sleep(API_DELAY)

    # ── Summary of fetch ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Fetch Summary")
    print("=" * 60)
    for year, count in year_counts.items():
        print(f"  {year}: {count} rows")
    print(f"  Total normalized rows: {len(all_rows)}")

    # ── DB Upsert ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DB Upsert")
    print("=" * 60)
    result = asyncio.run(upsert_to_db(all_rows))
    print(f"  Inserted: {result['inserted']}")
    print(f"  Updated:  {result['updated']}")
    print(f"  Skipped:  {result['skipped']}")

    # ── Final DB count ────────────────────────────────────────────
    total = asyncio.run(get_total_count())
    print(f"\n  Total rows in bea_gdp_by_industry: {total}")

    # ── Timeseries + 2024 ranking check ───────────────────────────
    asyncio.run(run_timeseries_check())


if __name__ == "__main__":
    main()
