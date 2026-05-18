"""
Pro Structural Context Engine.

Aggregates macroeconomic structural data and market price data for a specific domain
to provide analytical context for Pro Structural Briefs.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ExternalDataSeries,
    ExternalObservation,
    ExternalTradeFlow,
    ExternalIndustryStat,
    MarketDataInstrument,
    MarketDataPrice,
    AlertLog,
    Item
)
from analysis.pro_domain_config import (
    PRO_DOMAIN_CONFIG,
    get_pro_domain_config,
    infer_domain_from_topic
)

logger = logging.getLogger(__name__)

async def build_pro_structural_context(
    db: AsyncSession,
    alert_log: Optional[AlertLog] = None,
    domain_id: Optional[str] = None,
    topic: Optional[str] = None,
    lookback_days: int = 30
) -> Dict[str, Any]:
    """
    Builds a rich context dictionary for a Pro Structural Brief.
    """
    # 1. Resolve Domain ID
    resolved_domain_id = domain_id
    if not resolved_domain_id and alert_log:
        resolved_domain_id = infer_domain_from_topic(alert_log.topic)
    if not resolved_domain_id and topic:
        resolved_domain_id = infer_domain_from_topic(topic)
    if not resolved_domain_id:
        resolved_domain_id = "global_market_intelligence"
    
    config = get_pro_domain_config(resolved_domain_id)
    if not config:
        config = get_pro_domain_config("global_market_intelligence")
        resolved_domain_id = "global_market_intelligence"

    data_notes = []
    
    # 2. Signal / Alert Context
    signal_ctx = None
    related_news = []
    if alert_log:
        meta = alert_log.metadata_json or {}
        if "free_alert" in meta and "related_news" in meta["free_alert"]:
            related_news = meta["free_alert"]["related_news"]
        elif "evidence_list" in meta:
            # Fallback to evidence list if no structured related_news
            related_news = meta["evidence_list"]

        signal_ctx = {
            "alert_id": str(alert_log.id),
            "title": alert_log.target_label,
            "topic": alert_log.topic,
            "triggered_at": alert_log.triggered_at.isoformat() if alert_log.triggered_at else None,
            "related_news": related_news[:5] # Limit to top 5
        }

    # 3. Build Event Timeline from related_news with sequence-based role inference
    event_timeline = _build_event_timeline(related_news, signal_ctx)

    # 4. Structural Context Data
    structural_ctx = {
        "macro_observations": await _get_macro_observations(db, config, lookback_days, data_notes),
        "trade_flows": await _get_trade_flows(db, config, data_notes),
        "industry_stats": await _get_industry_stats(db, config, data_notes)
    }

    # 5. Market Confirmation Data
    market_ctx = await _get_market_confirmation(db, config, lookback_days, data_notes)

    # 6. Complement Watch Indicators
    watch_indicators = await _complement_watch_indicators(db, config.get("watch_indicators", []), data_notes)

    # 7. Build Final Context
    context = {
        "domain": {
            "domain_id": config["domain_id"],
            "display_name": config["display_name"],
            "primary_user_question": config["primary_user_question"],
            "primary_asset_classes": config["primary_asset_classes"],
            "decision_relevant_questions": config["decision_relevant_questions"]
        },
        "signal": signal_ctx,
        "event_timeline": event_timeline,
        "structural_context": structural_ctx,
        "market_confirmation": market_ctx,
        "watch_indicators": watch_indicators,
        "transmission_channels": config.get("transmission_channels", []),
        "exposure_targets": config.get("exposure_targets", []),
        "balanced_interpretations": config.get("balanced_interpretations", {}),
        "data_freshness": _calculate_freshness(structural_ctx, market_ctx),
        "data_notes": data_notes,
        # New analytical config fields (passed through for payload builder)
        "signal_classification_template": config.get("signal_classification_template", {}),
        "relevance_map": config.get("relevance_map", {}),
        "market_group_map": config.get("market_group_map", {}),
        "watch_conditions_template": config.get("watch_conditions_template", {}),
        "exposure_matrix_details": config.get("exposure_matrix_details", []),
        "market_group_interpretation": config.get("market_group_interpretation", {})
    }

    return context

async def _get_macro_observations(db: AsyncSession, config: dict, lookback_days: int, notes: list) -> List[dict]:
    """Fetch latest macro observations for integrated external sources."""
    s_data = config.get("structural_data", {})
    series_ids = (
        s_data.get("fred_series", [])
        + s_data.get("bls_series", [])
        + s_data.get("worldbank_indicators", [])
        + s_data.get("estat_series", [])
        + s_data.get("eia_series", [])
        + s_data.get("ecb_series", [])
        + s_data.get("bcb_series", [])
        + s_data.get("opec_series", [])
        + s_data.get("asean_series", [])
    )
    
    if not series_ids:
        return []

    results = []
    for s_id in series_ids:
        # Get latest observation
        stmt = select(ExternalObservation).where(
            ExternalObservation.series_id == s_id
        ).order_by(desc(ExternalObservation.date)).limit(1)
        
        obs_res = await db.execute(stmt)
        latest = obs_res.scalar_one_or_none()
        
        if not latest:
            notes.append(f"Macro series {s_id} not found in DB.")
            continue
            
        # Get previous observation for change calculation
        lookback_date = latest.date - timedelta(days=lookback_days)
        stmt_prev = select(ExternalObservation).where(
            ExternalObservation.series_id == s_id,
            ExternalObservation.date <= lookback_date
        ).order_by(desc(ExternalObservation.date)).limit(1)
        
        prev_res = await db.execute(stmt_prev)
        previous = prev_res.scalar_one_or_none()
        
        change_pct = None
        if previous and previous.value != 0 and latest.value is not None:
            change_pct = ((latest.value - previous.value) / abs(previous.value)) * 100

        results.append({
            "series_id": s_id,
            "source": latest.source,
            "latest_value": latest.value,
            "latest_date": latest.date.isoformat(),
            "period_label": latest.period_label,
            "previous_value": previous.value if previous else None,
            "change_pct": change_pct,
            "raw_json": latest.raw_json
        })
        
    return results

async def _get_trade_flows(db: AsyncSession, config: dict, notes: list) -> List[dict]:
    """Fetch recent trade flows for commodity codes."""
    codes = config.get("structural_data", {}).get("comtrade_commodity_codes", [])
    if not codes:
        return []

    stmt = select(ExternalTradeFlow).where(
        ExternalTradeFlow.commodity_id.in_(codes)
    ).order_by(desc(ExternalTradeFlow.year), desc(ExternalTradeFlow.trade_value)).limit(20)
    
    res = await db.execute(stmt)
    flows = res.scalars().all()
    
    if not flows:
        notes.append(f"No trade flows found for codes: {codes}")
        
    # Filter and Deduplicate flows
    best_flows = {}
    for f in flows:
        if f.trade_value is None or f.trade_value < 100000:
            continue
            
        key = (f.reporter_name, f.partner_name, f.flow_type, f.commodity_id, f.year)
        # Since stmt is ordered by trade_value DESC, the first one we see for a key is the max
        if key not in best_flows:
            best_flows[key] = {
                "reporter_name": f.reporter_name,
                "partner_name": f.partner_name,
                "flow_type": f.flow_type,
                "commodity_id": f.commodity_id,
                "commodity_name": f.commodity_name,
                "year": f.year,
                "period": f.period,
                "trade_value": f.trade_value,
                "quantity": f.quantity,
                "unit": f.unit
            }
            
    return list(best_flows.values())

async def _get_industry_stats(db: AsyncSession, config: dict, notes: list) -> List[dict]:
    """Fetch latest industry/regional statistics."""
    # Logic to filter by relevant metrics for the domain could be added here
    # For now, we take latest stats from BEA/Census
    stmt = select(ExternalIndustryStat).order_by(
        desc(ExternalIndustryStat.year), 
        desc(ExternalIndustryStat.value)
    ).limit(20)
    
    res = await db.execute(stmt)
    stats = res.scalars().all()
    
    if not stats:
        notes.append("No industry stats found in DB.")

    # Filtering logic by domain keywords
    keywords = config.get("structural_data", {}).get("industry_keywords", [])
    
    results = []
    for s in stats:
        industry_name = s.industry_name or ""
        # If keywords are defined, we prioritize them. If not, we take everything.
        if keywords:
            if not any(k.lower() in industry_name.lower() for k in keywords):
                continue
        
        results.append({
            "source": s.source,
            "dataset": s.dataset,
            "geo_name": s.geo_name,
            "industry_name": s.industry_name,
            "metric_name": s.metric_name,
            "year": s.year,
            "value": s.value,
            "unit": s.unit
        })
        
    return results

async def _get_market_confirmation(db: AsyncSession, config: dict, lookback_days: int, notes: list) -> Dict[str, Any]:
    """Fetch latest market data and calculate price changes."""
    m_data = config.get("market_data", {})
    symbols = m_data.get("alpha_vantage_symbols", []) + m_data.get("frankfurter_fx_pairs", [])
    
    if not symbols:
        return {"instruments": [], "latest_prices": []}

    latest_prices = []
    
    for symbol in symbols:
        # Get latest price and join with instrument to get asset_class
        stmt = (
            select(MarketDataPrice, MarketDataInstrument.asset_class)
            .join(MarketDataInstrument, MarketDataPrice.instrument_id == MarketDataInstrument.id)
            .where(MarketDataPrice.symbol == symbol)
            .order_by(desc(MarketDataPrice.date))
            .limit(1)
        )
        
        res_price = await db.execute(stmt)
        row = res_price.one_or_none()
        
        if not row:
            notes.append(f"Market data for {symbol} not yet synced.")
            continue
            
        latest = row[0]
        asset_class = row[1]
            
        # Get previous price
        lookback_date = latest.date - timedelta(days=lookback_days)
        stmt_prev = select(MarketDataPrice).where(
            MarketDataPrice.symbol == symbol,
            MarketDataPrice.date <= lookback_date
        ).order_by(desc(MarketDataPrice.date)).limit(1)
        
        res_prev = await db.execute(stmt_prev)
        previous = res_prev.scalar_one_or_none()
        
        change_pct = None
        # Use close price for change calculation
        if latest.close is not None and previous and previous.close and previous.close != 0:
            change_pct = ((latest.close - previous.close) / previous.close) * 100
            
        latest_prices.append({
            "provider": latest.provider,
            "symbol": latest.symbol,
            "asset_class": asset_class or "unknown",
            "latest_date": latest.date.isoformat(),
            "latest_close": latest.close,
            "previous_date": previous.date.isoformat() if previous else None,
            "previous_close": previous.close if previous else None,
            "percent_change": change_pct,
            "interval": latest.interval
        })
        
    return {
        "latest_prices": latest_prices
    }

async def _complement_watch_indicators(db: AsyncSession, indicators: List[dict], notes: list) -> List[dict]:
    """Add latest database values to watch indicator definitions."""
    results = []
    for ind in indicators:
        comp_ind = ind.copy()
        l_type = ind.get("lookup_type")
        s_id = ind.get("series_id") or ind.get("symbol")
        
        latest_val = None
        if l_type == "external_observation":
            stmt = select(ExternalObservation.value).where(
                ExternalObservation.series_id == s_id
            ).order_by(desc(ExternalObservation.date)).limit(1)
            latest_val = (await db.execute(stmt)).scalar_one_or_none()
        elif l_type == "trade_flow":
            stmt = select(ExternalTradeFlow.trade_value).where(
                ExternalTradeFlow.commodity_id == s_id
            ).order_by(desc(ExternalTradeFlow.year)).limit(1)
            latest_val = (await db.execute(stmt)).scalar_one_or_none()
        elif l_type == "market_price":
            stmt = select(MarketDataPrice.close).where(
                MarketDataPrice.symbol == s_id
            ).order_by(desc(MarketDataPrice.date)).limit(1)
            latest_val = (await db.execute(stmt)).scalar_one_or_none()
            
        comp_ind["latest_value"] = latest_val
        results.append(comp_ind)
        
    return results

def _calculate_freshness(structural: dict, market: dict) -> Dict[str, str]:
    """Identify the most recent data timestamps."""
    all_dates = []
    for obs in structural.get("macro_observations", []):
        if obs.get("latest_date"): all_dates.append(obs["latest_date"])
    for price in market.get("latest_prices", []):
        if price.get("latest_date"): all_dates.append(price["latest_date"])
        
    if not all_dates:
        return {"last_update": None}
        
    return {"last_update": max(all_dates)}

def _build_event_timeline(related_news: List[dict], signal_ctx: Optional[dict]) -> List[dict]:
    """
    Build an event timeline from related news items.
    - Sorted by timestamp (items without timestamp go to the end)
    - Role inference: trigger (first), then content-aware or sequence-based
    """
    if not related_news:
        return []

    # Keyword sets for content-aware role assignment
    _MARKET_KW = {"market", "stock", "etf", "bond", "yield", "price", "rally", "crash", "surge", "plunge", "trading"}
    _CONFIRM_KW = {"confirm", "verify", "report", "official", "statement", "announce"}

    raw = []
    for item in related_news[:8]:
        title = item.get("title") or item.get("headline") or item.get("text", "")
        source_url = item.get("url") or item.get("source_url") or item.get("link", "")
        timestamp = item.get("published") or item.get("timestamp") or item.get("date")
        location_label = item.get("location") or item.get("country") or None
        raw.append({
            "timestamp": timestamp,
            "title": title[:200] if title else "",
            "source_url": source_url,
            "location_label": location_label
        })

    # Sort: items with timestamps first (chronological), then items without
    def _sort_key(item: dict):
        ts = item.get("timestamp")
        if ts:
            return (0, str(ts))
        return (1, "")
    raw.sort(key=_sort_key)

    # Assign roles
    total = len(raw)
    for idx, item in enumerate(raw):
        title_lower = (item.get("title") or "").lower()
        if idx == 0:
            role = "trigger"
        elif any(kw in title_lower for kw in _MARKET_KW):
            role = "market_reaction"
        elif any(kw in title_lower for kw in _CONFIRM_KW):
            role = "confirmation"
        elif idx == total - 1 and total >= 3:
            role = "background"
        else:
            role = "context"
        item["role"] = role

    return raw

