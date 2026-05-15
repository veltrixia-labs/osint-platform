"""
BEA Pro Analysis Layer.

Integrates NIPA (Macro) and GDPbyIndustry (Sectoral) data to provide
quantitative summaries for Pro-level reports.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from data_sources.bea_query import (
    get_total_gdp_by_year,
    get_top_industries_by_year,
    get_industry_timeseries,
    get_sector_share
)
from data_sources.bea_nipa_query import (
    get_nipa_observation,
    get_gdp_current_dollars_timeseries,
    get_gdp_growth_rate_timeseries,
    get_pce_current_dollars_timeseries
)

logger = logging.getLogger(__name__)

def millions_to_trillions(val: float) -> float:
    return val / 1_000_000.0

def billions_to_trillions(val: float) -> float:
    return val / 1_000.0

async def get_macro_snapshot(session: AsyncSession, year: str) -> Dict[str, Any]:
    """
    Combines NIPA GDP level, growth, and PCE to give a macro overview.
    """
    gdp_lvl = await get_nipa_observation(session, "T10105", "1", year)
    gdp_growth = await get_nipa_observation(session, "T10101", "1", year)
    pce_lvl = await get_nipa_observation(session, "T20305", "1", year)

    res = {
        "year": year,
        "gdp_current_dollars_t": None,
        "gdp_growth_rate_pct": None,
        "pce_current_dollars_t": None,
        "pce_gdp_ratio_pct": None
    }

    if gdp_lvl:
        res["gdp_current_dollars_t"] = millions_to_trillions(gdp_lvl["data_value"])
    if gdp_growth:
        res["gdp_growth_rate_pct"] = gdp_growth["data_value"]
    if pce_lvl:
        res["pce_current_dollars_t"] = millions_to_trillions(pce_lvl["data_value"])
    
    if res["gdp_current_dollars_t"] and res["pce_current_dollars_t"]:
        res["pce_gdp_ratio_pct"] = round((res["pce_current_dollars_t"] / res["gdp_current_dollars_t"]) * 100, 2)

    return res

async def get_industry_snapshot(session: AsyncSession, year: str, top_n: int = 10) -> List[Dict[str, Any]]:
    """
    Returns top industries with their share of total GDP for the year.
    Uses sector_only=True to avoid double counting.
    """
    shares = await get_sector_share(session, year, sector_only=True)
    return shares[:top_n]

async def get_macro_industry_summary(session: AsyncSession, year: str) -> Dict[str, Any]:
    """
    Integrated summary of macro stats and key industry performers.
    """
    macro = await get_macro_snapshot(session, year)
    top_industries = await get_industry_snapshot(session, year, top_n=5)
    
    # Extract specific sectors for focus
    sectors_to_watch = {
        "Manufacturing": "31G",
        "Information": "51",
        "Finance and insurance": "52",
        "Real estate and rental and leasing": "53"
    }
    
    sector_values = {}
    for label, code in sectors_to_watch.items():
        ts = await get_industry_timeseries(session, code)
        val = next((r["data_value"] for r in ts if r["year"] == year), None)
        sector_values[label] = {
            "value_billions": val,
            "value_trillions": billions_to_trillions(val) if val is not None else None
        }

    return {
        "macro": macro,
        "top_5_sectors": top_industries,
        "key_sector_focus": sector_values
    }

async def get_growth_comparison(session: AsyncSession, start_year: str, end_year: str) -> Dict[str, Any]:
    """
    Compares growth across macro indicators and key industries.
    """
    # Macro Growth
    gdp_ts = await get_gdp_current_dollars_timeseries(session)
    pce_ts = await get_pce_current_dollars_timeseries(session)
    
    def get_val(ts, year):
        return next((r["data_value"] for r in ts if r["time_period"] == year), None)
    
    gdp_start = get_val(gdp_ts, start_year)
    gdp_end = get_val(gdp_ts, end_year)
    pce_start = get_val(pce_ts, start_year)
    pce_end = get_val(pce_ts, end_year)
    
    macro_growth = {
        "gdp_growth_pct": round(((gdp_end / gdp_start) - 1) * 100, 2) if gdp_start and gdp_end else None,
        "pce_growth_pct": round(((pce_end / pce_start) - 1) * 100, 2) if pce_start and pce_end else None,
    }

    # Industry Growth
    sectors = {
        "Manufacturing": "31G",
        "Information": "51",
        "Finance and insurance": "52",
        "Real estate and rental and leasing": "53",
        "Retail trade": "44RT",
        "Professional, scientific, and technical services": "54"
    }
    
    industry_growth = {}
    for label, code in sectors.items():
        ts = await get_industry_timeseries(session, code)
        val_s = next((r["data_value"] for r in ts if r["year"] == start_year), None)
        val_e = next((r["data_value"] for r in ts if r["year"] == end_year), None)
        if val_s and val_e:
            industry_growth[label] = round(((val_e / val_s) - 1) * 100, 2)

    return {
        "period": f"{start_year}-{end_year}",
        "macro_growth": macro_growth,
        "industry_growth": industry_growth
    }

async def get_covid_recovery_summary(session: AsyncSession) -> Dict[str, Any]:
    """
    Specifically analyzes the 2019 (Pre) -> 2020 (Shock) -> 2021 (Recovery) transition.
    """
    years = ["2019", "2020", "2021"]
    
    # 1. Macro indicators
    macro_stats = {}
    for y in years:
        macro_stats[y] = await get_macro_snapshot(session, y)
        
    # 2. Key sector changes
    sector_codes = {
        "Manufacturing": "31G",
        "Retail trade": "44RT",
        "Transportation and warehousing": "48TW",
        "Accommodation and food services": "72",
        "Information": "51"
    }
    
    sector_changes = {}
    for label, code in sector_codes.items():
        ts = await get_industry_timeseries(session, code)
        vals = {y: next((r["data_value"] for r in ts if r["year"] == y), None) for y in years}
        
        change_19_20 = round(((vals["2020"] / vals["2019"]) - 1) * 100, 2) if vals["2019"] and vals["2020"] else None
        change_20_21 = round(((vals["2021"] / vals["2020"]) - 1) * 100, 2) if vals["2020"] and vals["2021"] else None
        
        sector_changes[label] = {
            "drop_2020": change_19_20,
            "recovery_2021": change_20_21
        }

    return {
        "macro_trend": macro_stats,
        "sector_impacts": sector_changes
    }
