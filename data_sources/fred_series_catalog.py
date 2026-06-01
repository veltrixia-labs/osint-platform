"""
FRED Series Catalog.

Centralizes the series IDs and metadata for economic indicators used
in Pro reports and quantitative analysis.
"""

from typing import Any, Dict, List

FRED_SERIES_CATALOG = {
    "monetary_policy": [
        {
            "series_id": "FEDFUNDS",
            "name": "Effective Federal Funds Rate",
            "unit": "percent",
            "frequency_hint": "monthly",
            "pro_use": "policy_rate_context"
        },
        {
            "series_id": "DGS10",
            "name": "10-Year Treasury Constant Maturity Rate",
            "unit": "percent",
            "frequency_hint": "daily",
            "pro_use": "long_rate_context",
            "is_tradeable_macro": True,
            "display_label": "US 10-Year Treasury Yield",
            "accent_color": "#58a6ff",
            "transmission_unit_label": "% (annualised)"
        }
    ],
    "inflation": [
        {
            "series_id": "CPIAUCSL",
            "name": "Consumer Price Index for All Urban Consumers",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "inflation_context"
        }
    ],
    "energy": [
        {
            "series_id": "DCOILWTICO",
            "name": "WTI Crude Oil Price",
            "unit": "usd_per_barrel",
            "frequency_hint": "daily",
            "pro_use": "energy_price_context",
            "is_tradeable_macro": True,
            "display_label": "WTI Crude Oil (Spot)",
            "accent_color": "#eab308",
            "transmission_unit_label": "USD / barrel"
        },
        {
            "series_id": "GASREGW",
            "name": "U.S. City Average Retail Gasoline Price",
            "unit": "usd_per_gallon",
            "frequency_hint": "weekly",
            "pro_use": "gasoline_price_context"
        }
    ],
    "volatility": [
        {
            "series_id": "VIXCLS",
            "name": "CBOE Volatility Index: VIX",
            "unit": "index",
            "frequency_hint": "daily",
            "pro_use": "equity_volatility_context",
            "is_tradeable_macro": True,
            "display_label": "VIX (Volatility Index)",
            "accent_color": "#f87171",
            "transmission_unit_label": "Index (annualised %)"
        }
    ],
    "commodities": [
        {
            "series_id": "PCOPPUSDM",
            "name": "Global Price of Copper",
            "unit": "usd_per_metric_ton",
            "frequency_hint": "monthly",
            "pro_use": "industrial_commodity_context",
            "is_tradeable_macro": True,
            "display_label": "Global Copper Price",
            "accent_color": "#f97316",
            "transmission_unit_label": "USD / metric ton"
        }
    ],
    "geopolitical_risk": [
        {
            "series_id": "GPRH",
            "name": "Geopolitical Risk Index (historical)",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "geopolitical_risk_context"
        },
        {
            "series_id": "GPRHT",
            "name": "Geopolitical Risk Index — Threats",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "geopolitical_threat_context"
        },
        {
            "series_id": "GPRA",
            "name": "Geopolitical Risk Index — Acts",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "geopolitical_acts_context"
        }
    ],
    "currency": [
        {
            "series_id": "DTWEXBGS",
            "name": "Nominal Broad U.S. Dollar Index",
            "unit": "index",
            "frequency_hint": "daily",
            "pro_use": "usd_strength_context",
            "is_tradeable_macro": True,
            "display_label": "Broad USD Index",
            "accent_color": "#22d3ee",
            "transmission_unit_label": "Index (Jan-2006 = 100)"
        }
    ],
    "defense": [
        {
            "series_id": "FDEFX",
            "name": "Real National Defense Consumption Expenditures and Gross Investment",
            "unit": "billions_of_chained_2017_usd",
            "frequency_hint": "quarterly",
            "pro_use": "defense_spending_context"
        }
    ],
    "industrial": [
        {
            "series_id": "IPB53122S",
            "name": "Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "semi_production_context"
        },
        {
            "series_id": "IPI",
            "name": "Industrial Production Index",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "industrial_output_context"
        }
    ],
    "monetary": [
        {
            "series_id": "M2SL",
            "name": "M2 Money Stock",
            "unit": "billions_of_dollars",
            "frequency_hint": "monthly",
            "pro_use": "liquidity_context"
        }
    ],
    "supply_chain": [
        {
            "series_id": "PCU483111483111",
            "name": "Producer Price Index: Deep Sea Freight Transportation",
            "unit": "index",
            "frequency_hint": "monthly",
            "pro_use": "freight_cost_context"
        }
    ]
}

def get_all_fred_series() -> List[Dict[str, Any]]:
    """Return a flat list of all series in the catalog with their category."""
    all_series = []
    for category, series_list in FRED_SERIES_CATALOG.items():
        for series in series_list:
            entry = series.copy()
            entry["category"] = category
            all_series.append(entry)
    return all_series

def get_fred_series_by_category(category: str) -> List[Dict[str, Any]]:
    """Return all series belonging to a specific category."""
    return FRED_SERIES_CATALOG.get(category, [])

def get_fred_series_ids() -> List[str]:
    """Return a flat list of all series IDs in the catalog."""
    return [s["series_id"] for s in get_all_fred_series()]


def get_tradeable_macro_series() -> List[Dict[str, Any]]:
    """
    Return FRED series flagged as `is_tradeable_macro` — i.e. the curated set
    surfaced in the Dynamic Macro Selector (Hypothesis Testing Engine).
    Ordered by category for stable UI display.
    """
    out: List[Dict[str, Any]] = []
    for category, series_list in FRED_SERIES_CATALOG.items():
        for series in series_list:
            if not series.get("is_tradeable_macro"):
                continue
            entry = series.copy()
            entry["category"] = category
            out.append(entry)
    return out


def get_tradeable_macro_ids() -> List[str]:
    """Allowlist of macro series IDs accepted by the transmission engine."""
    return [s["series_id"] for s in get_tradeable_macro_series()]


def is_monthly_series(series_id: str) -> bool:
    """True iff the catalog entry for series_id has frequency_hint == 'monthly'."""
    for series in get_all_fred_series():
        if series["series_id"] == series_id:
            return (series.get("frequency_hint") or "").lower() == "monthly"
    return False
