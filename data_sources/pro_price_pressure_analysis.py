"""
BEA x BLS PPI Integrated Pro Analysis Layer.

Analyzes the relationship between industrial value-added growth (BEA)
and price pressure (BLS PPI) to identify economic signals like margin risk,
pricing power, or easing inflationary pressures.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from data_sources.bea_query import get_industry_timeseries
from data_sources.bls_ppi_query import (
    get_ppi_yoy_change,
    get_ppi_mom_change,
    get_ppi_period_change,
    get_ppi_latest
)

logger = logging.getLogger(__name__)

# PPI Series to BEA Industry Code Mapping
PPI_BEA_MAPPING = {
    "WPUFD4": {
        "label": "Final demand",
        "related_industries": ["GDP", "PVT"]
    },
    "WPUFD49104": {
        "label": "Final demand goods",
        "related_industries": ["31G", "PGOOD"]
    },
    "WPUFD49207": {
        "label": "Final demand services",
        "related_industries": ["PSERV"]
    },
    "WPU057": {
        "label": "Fuels and related products and power",
        "related_industries": ["21", "22", "48TW"]
    },
    "WPU101": {
        "label": "Iron and steel",
        "related_industries": ["31G", "23", "332"]
    },
    "WPU081": {
        "label": "Lumber and wood products",
        "related_industries": ["23", "321"]
    },
    "WPU114": {
        "label": "Machinery and equipment",
        "related_industries": ["333", "31G"]
    },
    "WPU117": {
        "label": "Electronic components and accessories",
        "related_industries": ["334", "51"]
    }
}

def get_ppi_bea_mapping() -> Dict[str, Any]:
    return PPI_BEA_MAPPING

async def get_industry_growth(
    session: AsyncSession, 
    industry_code: str, 
    start_year: str, 
    end_year: str
) -> Optional[float]:
    """Calculate BEA industry value-added growth rate (%) over a period."""
    ts = await get_industry_timeseries(session, industry_code)
    val_start = next((r["data_value"] for r in ts if r["year"] == start_year), None)
    val_end = next((r["data_value"] for r in ts if r["year"] == end_year), None)
    
    if val_start and val_end and val_start != 0:
        return round(((val_end - val_start) / val_start) * 100, 2)
    return None

async def get_industry_value_by_code(
    session: AsyncSession, 
    industry_code: str, 
    year: str
) -> Optional[float]:
    """Return BEA industry value in billions for a specific year."""
    ts = await get_industry_timeseries(session, industry_code)
    return next((r["data_value"] for r in ts if r["year"] == year), None)

def classify_pressure_signal(
    ppi_yoy: Optional[float], 
    ppi_cumulative: Optional[float], 
    industry_growth: Optional[float]
) -> str:
    """
    Classifies the relationship into a qualitative signal based on quantitative thresholds.
    """
    if ppi_yoy is None or ppi_cumulative is None or industry_growth is None:
        return "insufficient_data"

    if ppi_yoy > 5 and industry_growth < 10:
        return "margin_pressure_risk"
    if ppi_cumulative > 30 and industry_growth < ppi_cumulative:
        return "cost_pressure_outpacing_growth"
    if ppi_yoy < 0 and industry_growth > 10:
        return "price_pressure_easing_with_growth"
    if ppi_yoy > 3 and industry_growth > 20:
        return "growth_with_pricing_power"
    
    return "neutral_or_mixed"

async def analyze_price_pressure_vs_growth(
    session: AsyncSession,
    start_year: str = "2018",
    end_year: str = "2024",
    end_date: str = "2024-12"
) -> List[Dict[str, Any]]:
    """
    Integrated analysis of PPI changes vs related BEA industry growth.
    """
    analysis_results = []
    start_anchor_date = f"{start_year}-01"

    for series_id, info in PPI_BEA_MAPPING.items():
        # PPI Stats
        yoy = await get_ppi_yoy_change(session, series_id, end_date)
        cum = await get_ppi_period_change(session, series_id, start_anchor_date, end_date)
        latest = await get_ppi_latest(session, series_id)
        
        # Safely extract values from possibly-None results
        yoy_pct = yoy.get("change_percent") if yoy else None
        cum_pct = cum.get("change_percent") if cum else None
        latest_val = latest.get("value") if latest else None
        latest_date = latest.get("date") if latest else None

        # Industry Stats (aggregate or first primary)
        industries = info["related_industries"]
        for ind_code in industries:
            growth = await get_industry_growth(session, ind_code, start_year, end_year)
            ind_val = await get_industry_value_by_code(session, ind_code, end_year)
            
            signal = classify_pressure_signal(
                ppi_yoy=yoy_pct,
                ppi_cumulative=cum_pct,
                industry_growth=growth
            )
            
            analysis_results.append({
                "ppi_series_id": series_id,
                "ppi_label": info["label"],
                "ppi_yoy_pct": yoy_pct,
                "ppi_cumulative_pct": cum_pct,
                "ppi_latest_value": latest_val,
                "ppi_latest_date": latest_date,
                "bea_industry_code": ind_code,
                "bea_industry_growth_pct": growth,
                "bea_industry_value_billions": ind_val,
                "signal": signal
            })

    return analysis_results

async def get_price_pressure_summary(session: AsyncSession, end_date: str = "2024-12") -> Dict[str, Any]:
    """
    Consolidated summary for Pro reports highlighting risks and easing signals.
    """
    results = await analyze_price_pressure_vs_growth(session, end_date=end_date)
    
    risks = [r for r in results if r["signal"] in ["margin_pressure_risk", "cost_pressure_outpacing_growth"]]
    easing = [r for r in results if r["signal"] == "price_pressure_easing_with_growth"]
    pricing_power = [r for r in results if r["signal"] == "growth_with_pricing_power"]

    # Deduplicate risks (one series might hit multiple industries)
    def unique_by_series(items):
        seen = set()
        unique = []
        for i in items:
            if i["ppi_series_id"] not in seen:
                unique.append(i)
                seen.add(i["ppi_series_id"])
        return unique

    return {
        "as_of": end_date,
        "high_risk_series": unique_by_series(risks),
        "easing_pressure_series": unique_by_series(easing),
        "pricing_power_series": unique_by_series(pricing_power),
        "summary_metadata": {
            "total_series_analyzed": len(PPI_BEA_MAPPING),
            "risk_count": len(unique_by_series(risks)),
            "easing_count": len(unique_by_series(easing))
        }
    }
