"""
Test script for BEA industry classifier + sector_only queries.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_sources.bea_industry_classifier import classify_industry_code
from db.database import AsyncSessionLocal
from data_sources.bea_query import (
    get_total_gdp_by_year,
    get_top_industries_by_year,
    get_sector_share,
)


def test_classifier():
    """Verify classification of key codes."""
    test_cases = [
        ("GDP",     "total"),
        ("PVT",     "aggregate"),
        ("PSERV",   "aggregate"),
        ("FIRE",    "aggregate"),
        ("ICT",     "aggregate"),
        ("33DG",    "aggregate"),
        ("31ND",    "aggregate"),
        ("G",       "aggregate"),
        ("53",      "sector"),
        ("31G",     "sector"),
        ("44RT",    "sector"),
        ("48TW",    "sector"),
        ("11",      "sector"),
        ("6",       "sector"),
        ("7",       "sector"),
        ("531",     "subsector"),
        ("211",     "subsector"),
        ("481",     "subsector"),
        ("5412OP",  "detail"),
        ("3361MV",  "detail"),
        ("5415",    "detail"),
    ]

    print("=" * 60)
    print("Classifier Tests")
    print("=" * 60)
    all_pass = True
    for code, expected in test_cases:
        actual = classify_industry_code(code)
        status = "OK" if actual == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {code:>10s}  expected={expected:<12s}  actual={actual:<12s}  [{status}]")

    print(f"\n  Result: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    return all_pass


async def test_sector_queries():
    """Run sector_only queries and display results."""
    async with AsyncSessionLocal() as session:

        # ---- sector_only=True ranking ----
        print()
        print("=" * 60)
        print("Top Industries - sector_only=True (2022)")
        print("=" * 60)
        top = await get_top_industries_by_year(
            session, "2022", top_n=20, sector_only=True
        )
        for row in top:
            print(f"  #{row['rank']:>2}  {row['industry']:>6s}  "
                  f"${row['data_value']:>10,.1f}B  "
                  f"[{row['level']}]  {row['industry_description']}")

        # ---- sector_only=True share ----
        print()
        print("=" * 60)
        print("Sector Share - sector_only=True (2022)")
        print("=" * 60)
        shares = await get_sector_share(session, "2022", sector_only=True)

        gdp_total = None
        for row in shares:
            gdp_total = row["gdp_total"]
            bar = "#" * int(row["share_pct"])
            print(f"  {row['industry']:>6s}  {row['share_pct']:>5.2f}%  "
                  f"{bar}  {row['industry_description']}")

        total_share = sum(r["share_pct"] for r in shares)
        print(f"\n  GDP Total: ${gdp_total:,.1f}B" if gdp_total else "")
        print(f"  Sectors: {len(shares)}")
        print(f"  Share sum: {total_share:.2f}%")

        # ---- Compare with default (no sector_only) ----
        print()
        print("=" * 60)
        print("Comparison: default vs sector_only")
        print("=" * 60)
        shares_default = await get_sector_share(session, "2022", sector_only=False)
        total_default = sum(r["share_pct"] for r in shares_default)
        print(f"  Default (exclude_aggregates):  {len(shares_default)} rows,  sum = {total_default:.2f}%")
        print(f"  sector_only=True:              {len(shares)} rows,  sum = {total_share:.2f}%")


async def main():
    test_classifier()
    await test_sector_queries()


if __name__ == "__main__":
    asyncio.run(main())
