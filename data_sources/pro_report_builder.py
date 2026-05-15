"""
Pro Report Builder.

Orchestrates multiple analysis layers (BEA Macro, BEA Industry, BLS PPI)
to generate a consolidated quantitative report in JSON format.
"""

import logging
import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from data_sources.bea_pro_analysis import get_macro_snapshot, get_industry_snapshot
from data_sources.pro_price_pressure_analysis import (
    get_price_pressure_summary,
    analyze_price_pressure_vs_growth
)

logger = logging.getLogger(__name__)

async def build_pro_report(
    session: AsyncSession,
    as_of_year: str = "2024",
    as_of_date: str = "2024-12"
) -> Dict[str, Any]:
    """
    Builds a full Pro-tier report by aggregating various quantitative analyses.
    """
    
    # 1. Macro & Industry (BEA)
    macro = await get_macro_snapshot(session, as_of_year)
    industry = await get_industry_snapshot(session, as_of_year, top_n=10)
    
    # 2. Price Pressure (BLS PPI)
    # This internally calls analyze_price_pressure_vs_growth for some stats, 
    # but we also need the full list for signals.
    ppi_summary = await get_price_pressure_summary(session, as_of_date)
    
    # 3. Integrated Signals
    detailed_signals = await analyze_price_pressure_vs_growth(
        session, 
        start_year="2018",
        end_year=as_of_year, 
        end_date=as_of_date
    )
    
    # Filter signals into categories
    risk_signals = [
        r for r in detailed_signals 
        if r["signal"] in ["margin_pressure_risk", "cost_pressure_outpacing_growth"]
    ]
    pricing_power = [
        r for r in detailed_signals 
        if r["signal"] == "growth_with_pricing_power"
    ]
    easing_pressure = [
        r for r in detailed_signals 
        if r["signal"] == "price_pressure_easing_with_growth"
    ]

    report = {
        "report_type": "pro",
        "version": "0.1",
        "as_of_year": int(as_of_year),
        "as_of_date": as_of_date,
        "sections": {
            "macro_snapshot": macro,
            "industry_snapshot": industry,
            "price_pressure_summary": ppi_summary,
            "risk_signals": risk_signals,
            "pricing_power_signals": pricing_power,
            "easing_pressure_signals": easing_pressure
        },
        "metadata": {
            "data_sources": ["BEA GDPbyIndustry", "BEA NIPA", "BLS PPI"],
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "notes": [
                "Pro report uses quantitative data only.",
                "Expert interpretation is not included."
            ]
        }
    }
    
    return report
