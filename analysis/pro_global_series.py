"""
Global macro spine for Pro Structural Briefs.

CORE_GLOBAL_SERIES: tri-polar indicators always merged into macro context.
GLOBAL_RELEVANCE_MAP: display labels and up/down meanings for UI Section 06.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# --- Tri-polar "world thermometer" (always queried) ---
CORE_GLOBAL_SERIES: Dict[str, Dict[str, List[str]]] = {
    "us": {
        "fred_series": ["CPIAUCSL", "FEDFUNDS"],
    },
    "japan": {
        "estat_series": ["0003427113", "0004052177"],
    },
    "europe": {
        "ecb_series": [
            "ICP.M.U2.N.000000.4.ANR",
            "FM.D.U2.EUR.4F.KR.MRR_RT.LEV",
        ],
    },
}

# One headline indicator per pole for Section 06 priority tier
CORE_GLOBAL_REPRESENTATIVE_IDS: List[str] = [
    "CPIAUCSL",
    "0003427113",
    "ICP.M.U2.N.000000.4.ANR",
]

# Per-pole pick order: CPI (or inflation) first, then policy rate, then other core series
CORE_GLOBAL_POLE_PICK_ORDER: Dict[str, List[str]] = {
    "us": ["CPIAUCSL", "FEDFUNDS"],
    "japan": ["0003427113", "0004052177"],
    "europe": ["ICP.M.U2.N.000000.4.ANR", "FM.D.U2.EUR.4F.KR.MRR_RT.LEV"],
}

STRUCTURAL_SERIES_KEYS = (
    "fred_series",
    "bls_series",
    "worldbank_indicators",
    "estat_series",
    "eia_series",
    "ecb_series",
    "bcb_series",
    "opec_series",
    "asean_series",
)

ENERGY_SUPPLY_MACRO_IDS = {
    "crude_price": "DCOILWTICO",
    "crude_inventory": "WCESTUS1",
}

# Hormuz / energy-geopolitics priority (FRED + EIA + OPEC in domain config)
ENERGY_GEOPOLITICAL_SERIES_IDS = [
    "DCOILWTICO",
    "GASREGW",
    "GPRH",
    "GPRHT",
    "GPRA",
    "WCESTUS1",
    "WPULEUS3",
    "WCRFPUS2",
]

MIN_MACRO_DISPLAY_CARDS = 6
MAX_MACRO_DISPLAY_CARDS = 12

# display_name + directional meanings for all synced global sources
GLOBAL_RELEVANCE_MAP: Dict[str, Dict[str, str]] = {
  # US / FRED
    "CPIAUCSL": {
        "display_name": "US CPI (headline)",
        "up_meaning": "Sticky US inflation; tighter Fed reaction function likely.",
        "down_meaning": "Disinflation progress; room for slower tightening or cuts.",
    },
    "FEDFUNDS": {
        "display_name": "US Federal Funds Rate",
        "up_meaning": "Tighter US financial conditions; stronger USD bias.",
        "down_meaning": "Easier US policy; support for risk assets and duration.",
    },
    "DGS10": {
        "display_name": "US 10Y Treasury yield",
        "up_meaning": "Higher discount rates; pressure on growth valuations.",
        "down_meaning": "Lower term premium; supportive for bonds and equities.",
    },
    "DCOILWTICO": {
        "display_name": "WTI crude oil (spot)",
        "up_meaning": "Supply shock or demand strength; inflation and petro-FX stress.",
        "down_meaning": "Demand destruction or supply relief; inflation headwind eases.",
    },
    "GPRH": {
        "display_name": "Geopolitical Risk Index (GPR)",
        "up_meaning": "Elevated geopolitical stress; safe-haven and energy risk premia.",
        "down_meaning": "Geopolitical risk easing; supports risk assets and trade lanes.",
    },
    "GPRHT": {
        "display_name": "GPR — Threats sub-index",
        "up_meaning": "Rising threat rhetoric and conflict risk around chokepoints.",
        "down_meaning": "Threat intensity moderating versus recent peaks.",
    },
    "GPRA": {
        "display_name": "GPR — Acts sub-index",
        "up_meaning": "Material geopolitical acts (sanctions, strikes, closures) increasing.",
        "down_meaning": "Fewer realized geopolitical acts in the observation window.",
    },
    "GASREGW": {
        "display_name": "US retail gasoline price",
        "up_meaning": "Consumer energy burden rising; political sensitivity increases.",
        "down_meaning": "Pump price relief; household real income support.",
    },
    "DTWEXBGS": {
        "display_name": "Broad US dollar index",
        "up_meaning": "USD strength; EM and commodity importers under pressure.",
        "down_meaning": "USD weakness; global liquidity and EM risk-on support.",
    },
    "M2SL": {
        "display_name": "US M2 money stock",
        "up_meaning": "Liquidity expansion; supports risk assets (with lag).",
        "down_meaning": "Liquidity contraction; tighter financial conditions.",
    },
    "IPB53122S": {
        "display_name": "US industrial production (semi)",
        "up_meaning": "Manufacturing momentum; capacity utilization rising.",
        "down_meaning": "Industrial slowdown; inventory cycle risk.",
    },
    # US / BLS
    "WPU05": {
        "display_name": "US PPI fuels & energy",
        "up_meaning": "Upstream energy cost pressure feeding wholesale prices.",
        "down_meaning": "Producer energy costs easing; margin relief downstream.",
    },
    "WPU051": {
        "display_name": "US PPI petroleum products",
        "up_meaning": "Refined product inflation; margin squeeze for consumers.",
        "down_meaning": "Refined product deflation; refining margin normalization.",
    },
    "WPUFD4": {
        "display_name": "US PPI final demand",
        "up_meaning": "Broad producer inflation; margin compression risk.",
        "down_meaning": "Producer disinflation; downstream CPI may follow.",
    },
    "PCU334413334413": {
        "display_name": "US PPI semiconductors",
        "up_meaning": "Chip input costs rising; margin pressure on OEMs.",
        "down_meaning": "Semi input deflation; supports device pricing power.",
    },
    # Japan / e-Stat
    "0003427113": {
        "display_name": "Japan CPI (2020 base)",
        "up_meaning": "Domestic inflation firming; BoJ normalization risk rises.",
        "down_meaning": "Japan disinflation; sustained ultra-loose policy bias.",
    },
    "0004052177": {
        "display_name": "Japan IIP — production (2020=100)",
        "up_meaning": "Manufacturing cycle strengthening; export engine warming.",
        "down_meaning": "Industrial output contraction; Asia supply chain softening.",
    },
    # Europe / ECB
    "ICP.M.U2.N.000000.4.ANR": {
        "display_name": "Euro area HICP (YoY)",
        "up_meaning": "ECB may stay restrictive; EUR real rates supportive.",
        "down_meaning": "ECB cut path more likely; duration rally potential.",
    },
    "FM.D.U2.EUR.4F.KR.MRR_RT.LEV": {
        "display_name": "ECB main refinancing rate",
        "up_meaning": "Tighter euro-area conditions; bank NIM support.",
        "down_meaning": "Euro-area easing; credit impulse turning supportive.",
    },
    "EXR.D.USD.EUR.SP00.A": {
        "display_name": "EUR/USD reference rate",
        "up_meaning": "EUR strengthening vs USD; easier euro-area financial conditions abroad.",
        "down_meaning": "EUR weakening; export competitiveness rises but import inflation risk.",
    },
    # EIA
    "WCESTUS1": {
        "display_name": "US crude inventories (ex-SPR)",
        "up_meaning": "Stock build — oversupply or weak demand signal.",
        "down_meaning": "Stock draw — tight physical market / supply-driven bid.",
    },
    "WPULEUS3": {
        "display_name": "US refinery utilization",
        "up_meaning": "High utilization; strong downstream demand for crude.",
        "down_meaning": "Low utilization; maintenance or demand softness.",
    },
    "WCRFPUS2": {
        "display_name": "US field crude production",
        "up_meaning": "US supply growth; OPEC+ market share pressure.",
        "down_meaning": "US supply restraint; supports global balances.",
    },
    # OPEC / KAPSARC
    "OPEC.CRUDE_PRODUCTION": {
        "display_name": "OPEC crude production",
        "up_meaning": "Cartel supply addition; bearish for prompt prices unless demand matches.",
        "down_meaning": "OPEC supply restraint; supports price floor.",
    },
    "WORLD.CRUDE_PRODUCTION": {
        "display_name": "World crude production",
        "up_meaning": "Global supply expansion; bearish unless demand surprise.",
        "down_meaning": "Global supply contraction; structural tightness.",
    },
    # Brazil / BCB
    "BCB.11": {
        "display_name": "Brazil Selic (policy)",
        "up_meaning": "Tight EM policy; risk-off for high-beta assets.",
        "down_meaning": "EM easing cycle; carry and commodity support.",
    },
    "BCB.1": {
        "display_name": "USD/BRL (PTAX)",
        "up_meaning": "BRL weakening (USD/BRL up) — EM stress, capital outflows.",
        "down_meaning": "BRL strengthening — risk-on for LatAm assets.",
    },
    "BCB.433": {
        "display_name": "Brazil IPCA (monthly)",
        "up_meaning": "EM inflation surprise; BCB may stay hawkish.",
        "down_meaning": "EM disinflation; rate-cut path opens.",
    },
    # ASEAN
    "FDI.AMS.TOT.INF": {
        "display_name": "ASEAN total FDI inflows",
        "up_meaning": "Supply-chain relocation and regional investment boom.",
        "down_meaning": "FDI slowdown; near-shoring narrative weakening.",
    },
    "IMTS.Annually": {
        "display_name": "ASEAN trade in goods",
        "up_meaning": "Regional trade expansion; manufacturing hub strength.",
        "down_meaning": "Trade contraction; demand or logistics disruption.",
    },
    # World Bank (composite IDs vary; map common config keys)
    "NY.GDP.MKTP.CD": {
        "display_name": "GDP (current USD)",
        "up_meaning": "Nominal output expansion in USD terms.",
        "down_meaning": "Nominal GDP contraction or FX-driven decline.",
    },
    "NY.GDP.MKTP.KD.ZG": {
        "display_name": "Real GDP growth (%)",
        "up_meaning": "Growth acceleration; cyclical risk-on support.",
        "down_meaning": "Growth slowdown; recession risk rising.",
    },
    "FP.CPI.TOTL.ZG": {
        "display_name": "Consumer price inflation (%)",
        "up_meaning": "Global inflation pressure; policy stays restrictive.",
        "down_meaning": "Global disinflation; easing cycle possible.",
    },
    # Tri-polar market instruments (Section 07)
    "N225": {
        "display_name": "Nikkei 225",
        "up_meaning": "Japan risk-on; yen carry and export sentiment supportive.",
        "down_meaning": "Japan risk-off; BoJ/Fx or global growth concerns.",
    },
    "DAX": {
        "display_name": "DAX (Germany)",
        "up_meaning": "European cyclical optimism; export/industrial bid.",
        "down_meaning": "European growth fears; energy or China drag.",
    },
    "EURUSD": {
        "display_name": "EUR/USD",
        "up_meaning": "EUR strength vs USD; easier euro-area financial conditions abroad.",
        "down_meaning": "EUR weakness; USD liquidity dominance.",
    },
    "USDJPY": {
        "display_name": "USD/JPY",
        "up_meaning": "USD strength vs JPY — BoJ divergence, carry unwind risk for Japan.",
        "down_meaning": "JPY strength — risk-off or BoJ hawkish repricing.",
    },
    "EWJ": {
        "display_name": "MSCI Japan ETF (EWJ)",
        "up_meaning": "Japan equity risk-on proxy.",
        "down_meaning": "Japan equity risk-off proxy.",
    },
    "EWG": {
        "display_name": "MSCI Germany ETF (EWG)",
        "up_meaning": "Europe cyclical equity bid (Germany proxy).",
        "down_meaning": "Europe equity risk-off (Germany proxy).",
    },
}


def get_core_global_series_ids() -> List[str]:
    """Flat, deduplicated list of all CORE_GLOBAL_SERIES IDs."""
    seen: set[str] = set()
    ordered: List[str] = []
    for region in CORE_GLOBAL_SERIES.values():
        for key in STRUCTURAL_SERIES_KEYS:
            for sid in region.get(key, []):
                if sid not in seen:
                    seen.add(sid)
                    ordered.append(sid)
    return ordered


def flatten_structural_series_ids(structural_data: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for key in STRUCTURAL_SERIES_KEYS:
        ids.extend(structural_data.get(key, []))
    return ids


def merge_relevance_maps(domain_map: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, str]]:
    """Domain entries override display text; global entries provide up/down meanings."""
    merged: Dict[str, Dict[str, str]] = {
        sid: dict(meta) for sid, meta in GLOBAL_RELEVANCE_MAP.items()
    }
    for sid, val in (domain_map or {}).items():
        if isinstance(val, dict):
            merged[sid] = {**merged.get(sid, {}), **val}
        else:
            base = merged.get(sid, {})
            merged[sid] = {
                "display_name": str(val),
                "up_meaning": base.get("up_meaning", ""),
                "down_meaning": base.get("down_meaning", ""),
            }
    return merged


def relevance_display_name(merged_map: Dict[str, Dict[str, str]], series_id: str) -> str:
    entry = merged_map.get(series_id)
    if isinstance(entry, dict):
        return entry.get("display_name") or series_id
    return series_id or str(entry)


def trend_meaning_for_observation(
    merged_map: Dict[str, Dict[str, str]], series_id: str, change_pct: Optional[float]
) -> Optional[str]:
    if change_pct is None:
        return None
    entry = merged_map.get(series_id)
    if not isinstance(entry, dict):
        return None
    if change_pct > 0:
        return entry.get("up_meaning") or None
    if change_pct < 0:
        return entry.get("down_meaning") or None
    return None


def _pick_global_base_series(by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    """Slots 1–3: one CPI/rate (or core) per pole — US, Japan, Europe."""
    picked: List[str] = []
    for _pole, candidates in CORE_GLOBAL_POLE_PICK_ORDER.items():
        for sid in candidates:
            if sid in by_id and sid not in picked:
                picked.append(sid)
                break
    return picked


def select_quantitative_context_cards(
    observations: List[Dict[str, Any]],
    domain_id: str,
    structural_data: Dict[str, Any],
    *,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """
    Slots 1–3: fixed global base (US / Japan / Europe).
    Slots 4–6: largest |change_pct| among non-core series (EIA, OPEC, PPI, etc.).
    """
    by_id = {o["series_id"]: o for o in observations if o.get("series_id")}
    core_set = set(get_core_global_series_ids())

    global_slots = _pick_global_base_series(by_id)[:3]

    dynamic_pool = [
        o
        for o in observations
        if o.get("series_id") not in global_slots and o.get("series_id") not in core_set
    ]
    dynamic_sorted = sorted(
        dynamic_pool,
        key=lambda o: abs(o.get("change_pct") or 0),
        reverse=True,
    )
    dynamic_ids = [o["series_id"] for o in dynamic_sorted if o.get("series_id")]

    # If domain series are in core_set but not picked globally, allow them in dynamic pool
    if len(dynamic_ids) < 3:
        extra = [
            o
            for o in observations
            if o.get("series_id") not in global_slots
            and o.get("series_id") not in dynamic_ids
            and o.get("series_id") not in core_set
        ]
        extra_sorted = sorted(
            extra,
            key=lambda o: abs(o.get("change_pct") or 0),
            reverse=True,
        )
        for o in extra_sorted:
            sid = o.get("series_id")
            if sid and sid not in global_slots and sid not in dynamic_ids:
                dynamic_ids.append(sid)
            if len(dynamic_ids) >= 3:
                break

    selected_ids = global_slots + dynamic_ids[:3]
    return [by_id[sid] for sid in selected_ids[:limit] if sid in by_id]


def _synthetic_macro_card(
    series_id: str,
    display_name: str,
    *,
    source: str = "domain_config",
    latest_value: Any = "—",
    change_pct: Optional[float] = None,
    trend_meaning: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "series_id": series_id,
        "source": source,
        "latest_value": latest_value,
        "latest_date": None,
        "change_pct": change_pct,
        "display_name": display_name,
        "trend_meaning": trend_meaning,
        "is_synthetic": True,
    }


def pad_macro_display_cards(
    context: Dict[str, Any],
    cards: List[Dict[str, Any]],
    *,
    min_cards: int = MIN_MACRO_DISPLAY_CARDS,
    max_cards: int = MAX_MACRO_DISPLAY_CARDS,
) -> List[Dict[str, Any]]:
    """
    When external_observations are sparse, fill Section 06 density from market
    movers, watch indicators, and domain-config structural matrices.
    """
    if len(cards) >= min_cards:
        return cards[:max_cards]

    out = list(cards)
    seen = {c.get("series_id") for c in out if c.get("series_id")}
    relevance = context.get("relevance_map") or {}
    if relevance and not isinstance(next(iter(relevance.values()), None), dict):
        relevance = merge_relevance_maps(relevance)

    m_ctx = context.get("market_confirmation") or {}
    for price in m_ctx.get("latest_prices") or []:
        if len(out) >= min_cards:
            break
        sym = price.get("symbol")
        if not sym or sym in seen:
            continue
        pct = price.get("percent_change")
        meaning = None
        if pct is not None:
            meaning = (
                "Market confirmation signal (synthetic macro slot)."
                if abs(pct) <= 0.1
                else f"Market mover {pct:+.2f}% over lookback (fills sparse macro DB)."
            )
        out.append(
            _synthetic_macro_card(
                f"MARKET::{sym}",
                f"{sym} (market)",
                source="market_data",
                latest_value=price.get("latest_price"),
                change_pct=pct,
                trend_meaning=meaning,
            )
        )
        seen.add(f"MARKET::{sym}")

    for idx, w in enumerate(context.get("watch_indicators") or []):
        if len(out) >= min_cards:
            break
        label = w.get("indicator") or w.get("series_id") or f"Watch {idx + 1}"
        sid = f"WATCH::{label[:40]}"
        if sid in seen:
            continue
        out.append(
            _synthetic_macro_card(
                sid,
                label,
                source=w.get("source", "watch_indicator"),
                latest_value=w.get("latest_value", "—"),
                trend_meaning=w.get("why_it_matters"),
            )
        )
        seen.add(sid)

    for idx, channel in enumerate(context.get("transmission_channels") or []):
        if len(out) >= min_cards:
            break
        sid = f"CHANNEL::{idx}"
        if sid in seen:
            continue
        out.append(
            _synthetic_macro_card(
                sid,
                f"Transmission: {channel}",
                source="domain_config",
                trend_meaning="Rule-based transmission channel from domain matrix.",
            )
        )
        seen.add(sid)

    for idx, exp in enumerate(context.get("exposure_matrix_details") or []):
        if len(out) >= min_cards:
            break
        target = exp.get("target") or f"Exposure {idx + 1}"
        sid = f"EXPOSURE::{target[:32]}"
        if sid in seen:
            continue
        sens = (exp.get("sensitivity") or "medium").upper()
        out.append(
            _synthetic_macro_card(
                sid,
                f"Exposure: {target}",
                source="domain_config",
                latest_value=sens,
                trend_meaning=exp.get("reason") or exp.get("transmission"),
            )
        )
        seen.add(sid)

    domain = context.get("domain") or {}
    for idx, q in enumerate(domain.get("decision_relevant_questions") or []):
        if len(out) >= min_cards:
            break
        sid = f"QUESTION::{idx}"
        if sid in seen:
            continue
        out.append(
            _synthetic_macro_card(
                sid,
                "Decision lens",
                source="domain_config",
                latest_value="—",
                trend_meaning=q,
            )
        )
        seen.add(sid)

    for sid, meta in list(relevance.items()):
        if len(out) >= min_cards:
            break
        if sid in seen or sid.startswith(("FALLBACK::", "MARKET::", "WATCH::")):
            continue
        if isinstance(meta, dict) and meta.get("display_name"):
            out.append(
                _synthetic_macro_card(
                    f"RELEVANCE::{sid}",
                    meta["display_name"],
                    source="relevance_map",
                    trend_meaning=meta.get("up_meaning") or "Configured structural relevance (awaiting live observation).",
                )
            )
            seen.add(f"RELEVANCE::{sid}")

    return out[:max_cards]


def energy_supply_driven_market_status(
    domain_id: str, macro_observations: List[Dict[str, Any]]
) -> Optional[str]:
    """Crude up + US inventory draw => supply-driven confirmation."""
    if domain_id != "energy_resource_risk":
        return None
    by_id = {o["series_id"]: o for o in macro_observations}
    crude = by_id.get(ENERGY_SUPPLY_MACRO_IDS["crude_price"], {})
    inv = by_id.get(ENERGY_SUPPLY_MACRO_IDS["crude_inventory"], {})
    crude_chg = crude.get("change_pct")
    inv_chg = inv.get("change_pct")
    if crude_chg is None or inv_chg is None:
        return None
    if crude_chg > 0.5 and inv_chg < -0.5:
        return "Strongly Confirming (Supply-Driven)"
    return None
