"""
Pro Structural Context Engine.

Aggregates macroeconomic structural data and market price data for a specific domain
to provide analytical context for Pro Structural Briefs.
"""

import re
import uuid
import logging
from typing import Optional, List, Dict, Any, Set
from datetime import datetime, timedelta, timezone
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
    infer_domain_from_topic,
)
from analysis.pro_global_series import (
    get_core_global_series_ids,
    merge_relevance_maps,
)
from analysis.pro_structural_compiler import (
    MIN_ALERT_CORRELATION,
    MIN_NEWS_CORRELATION,
    _tokenize,
    build_dynamic_structural_title,
    build_sector_vocabulary,
    filter_correlated_news_items,
    filter_correlated_timeline_events,
    structural_correlation_score,
)
from reports.text_encoding import sanitize_unicode_text, sanitize_unicode_tree

logger = logging.getLogger(__name__)

# Live alert clustering window (aligned with jobs.pro_generation_policy)
ALERT_CLUSTER_WINDOW_HOURS = 24


async def resolve_latest_domain_alert(
    db: AsyncSession,
    domain_id: str,
    *,
    window_hours: int = ALERT_CLUSTER_WINDOW_HOURS,
) -> Optional[AlertLog]:
    """
    Pick the highest-scoring alert in the live clustering window for a Pro domain.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    stmt = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= since,
            AlertLog.suppressed == False,  # noqa: E712
        )
        .order_by(desc(AlertLog.triggered_at), desc(AlertLog.intelligence_score))
        .limit(120)
    )
    rows = (await db.execute(stmt)).scalars().all()
    best: Optional[AlertLog] = None
    best_score = -1.0
    for row in rows:
        if infer_domain_from_topic(row.topic or "") != domain_id:
            continue
        score = float(row.intelligence_score or 0.0)
        if best is None or score > best_score:
            best = row
            best_score = score
    return best


def _build_predictive_forecast(
    domain_id: str,
    domain_display: str,
    macro_obs: List[dict],
    market_ctx: dict,
    *,
    alert_depleted: bool,
) -> Dict[str, Any]:
    """
    Rule-based macro risk outlook when the 24h alert cluster is empty.
    Keeps the intelligence stream alive without LLM dependency.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    risk_vectors: List[str] = []
    for obs in (macro_obs or [])[:8]:
        chg = obs.get("change_pct")
        label = obs.get("display_name") or obs.get("series_id") or "Macro series"
        if chg is None:
            continue
        if chg > 0.75:
            risk_vectors.append(f"{label}: upward structural pressure ({chg:+.2f}% lookback)")
        elif chg < -0.75:
            risk_vectors.append(f"{label}: downward structural pressure ({chg:+.2f}% lookback)")
        else:
            risk_vectors.append(f"{label}: range-bound ({chg:+.2f}% lookback)")

    prices = market_ctx.get("latest_prices") or []
    for price in prices[:4]:
        pct = price.get("percent_change")
        sym = price.get("symbol") or "Instrument"
        if pct is None:
            continue
        risk_vectors.append(f"{sym}: session move {pct:+.2f}% (market confirmation layer)")

    mode = "macro_predictive" if alert_depleted else "alert_anchored"
    if alert_depleted and not risk_vectors:
        risk_vectors.append(
            f"No live alerts in the last {ALERT_CLUSTER_WINDOW_HOURS}h; "
            "quantitative feeds are the sole active signal layer."
        )

    headline = (
        f"Predictive structural outlook for {domain_display}: "
        + (risk_vectors[0] if risk_vectors else "monitoring macro and market feeds in real time.")
    )
    return {
        "mode": mode,
        "generated_at": generated_at,
        "headline": headline,
        "risk_vectors": risk_vectors,
        "confidence": "moderate" if len(risk_vectors) >= 2 else "low",
        "alert_cluster_depleted": alert_depleted,
    }


async def build_pro_structural_context(
    db: AsyncSession,
    alert_log: Optional[AlertLog] = None,
    domain_id: Optional[str] = None,
    topic: Optional[str] = None,
    lookback_days: int = 30,
    *,
    force_rebuild: bool = True,
    analysis_generated_at: Optional[datetime] = None,
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
    analysis_ts = analysis_generated_at or datetime.now(timezone.utc)

    # 2. Signal / Alert Context — bind to 24h domain cluster when no explicit alert
    if not alert_log and resolved_domain_id:
        alert_log = await resolve_latest_domain_alert(db, resolved_domain_id)
        if alert_log:
            data_notes.append(
                f"Anchored to latest {ALERT_CLUSTER_WINDOW_HOURS}h domain alert cluster."
            )
        else:
            data_notes.append(
                f"No alerts in the last {ALERT_CLUSTER_WINDOW_HOURS}h for this domain; "
                "using macro predictive forecasting layer."
            )

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
            "title": sanitize_unicode_text(alert_log.target_label or ""),
            "topic": alert_log.topic,
            "triggered_at": alert_log.triggered_at.isoformat() if alert_log.triggered_at else None,
            "source_url": _first_evidence_url(meta),
            "related_news": related_news[:5]  # Limit to top 5
        }

    merged_relevance = merge_relevance_maps(config.get("relevance_map", {}))
    sector_vocabulary = build_sector_vocabulary(config, merged_relevance)
    trigger_tokens: Set[str] = set()
    if signal_ctx and signal_ctx.get("title"):
        trigger_tokens = _tokenize(signal_ctx["title"])

    related_news = filter_correlated_news_items(
        related_news,
        sector_vocabulary,
        trigger_tokens=trigger_tokens,
    )
    if signal_ctx:
        signal_ctx["related_news"] = related_news[:5]

    related_events = await _fetch_related_alert_events(
        db,
        alert_log,
        resolved_domain_id,
        data_notes,
        limit=8,
        window_hours=ALERT_CLUSTER_WINDOW_HOURS,
        vocabulary=sector_vocabulary,
        trigger_tokens=trigger_tokens,
    )

    # 3. Event timeline: correlated domain alerts + news only
    event_timeline = _build_event_timeline(
        related_news,
        signal_ctx,
        related_events=related_events,
        vocabulary=sector_vocabulary,
        trigger_tokens=trigger_tokens,
    )

    # 4. Structural Context Data
    structural_ctx = {
        "macro_observations": await _get_macro_observations(
            db, config, lookback_days, data_notes, resolved_domain_id
        ),
        "trade_flows": await _get_trade_flows(db, config, data_notes),
        "industry_stats": await _get_industry_stats(db, config, data_notes)
    }

    # 5. Market Confirmation Data
    market_ctx = await _get_market_confirmation(db, config, lookback_days, data_notes)

    # 6. Complement Watch Indicators
    watch_indicators = await _complement_watch_indicators(db, config.get("watch_indicators", []), data_notes)

    alert_depleted = alert_log is None and not related_events
    predictive_forecast = _build_predictive_forecast(
        resolved_domain_id,
        config.get("display_name", resolved_domain_id),
        structural_ctx.get("macro_observations") or structural_ctx.get("macro_display_cards") or [],
        market_ctx,
        alert_depleted=alert_depleted,
    )

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
        "related_events": related_events,
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
        "relevance_map": merged_relevance,
        "market_group_map": config.get("market_group_map", {}),
        "watch_conditions_template": config.get("watch_conditions_template", {}),
        "exposure_matrix_details": config.get("exposure_matrix_details", []),
        "market_group_interpretation": config.get("market_group_interpretation", {}),
        "predictive_forecast": predictive_forecast,
        "analysis_generated_at": analysis_ts.isoformat(),
        "force_rebuild": force_rebuild,
        "alert_cluster_window_hours": ALERT_CLUSTER_WINDOW_HOURS,
        "realtime_mode": True,
    }

    context["brief_title"] = build_dynamic_structural_title(context)
    context = sanitize_unicode_tree(context)

    return context

async def _get_macro_observations(
    db: AsyncSession,
    config: dict,
    lookback_days: int,
    notes: list,
    domain_id: str,
) -> List[dict]:
    """Fetch latest macro observations for domain + global core series."""
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
    for core_id in get_core_global_series_ids():
        if core_id not in series_ids:
            series_ids.append(core_id)

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

def _topic_match_keywords(
    domain_id: str, topic: Optional[str], trigger_label: Optional[str]
) -> Set[str]:
    """Keywords for matching related alerts in the same narrative thread."""
    keywords: Set[str] = set()
    for token in re.split(r"[_\s\-]+", domain_id or ""):
        if len(token) >= 4:
            keywords.add(token.lower())
    for token in re.split(r"[_\s\-]+", topic or ""):
        if len(token) >= 4:
            keywords.add(token.lower())
    if trigger_label:
        for token in re.findall(r"[A-Za-z]{4,}", trigger_label):
            keywords.add(token.lower())
    return keywords


def _alert_matches_domain_context(
    row: AlertLog, domain_id: str, keywords: Set[str]
) -> bool:
    row_domain = infer_domain_from_topic(row.topic or "")
    if row_domain == domain_id or (row.topic or "") == domain_id:
        return True
    label = (row.target_label or "").lower()
    return bool(keywords) and any(kw in label for kw in keywords)


def _first_evidence_url(meta: Optional[dict]) -> Optional[str]:
    """Primary external URL from alert metadata evidence_list."""
    if not meta:
        return None
    for item in meta.get("evidence_list") or []:
        url = item.get("url") or item.get("link") or item.get("source_url")
        if url and str(url).strip():
            return str(url).strip()
    return None


async def _fetch_related_alert_events(
    db: AsyncSession,
    alert_log: Optional[AlertLog],
    domain_id: str,
    notes: list,
    *,
    limit: int = 8,
    lookback_days: Optional[int] = None,
    window_hours: Optional[int] = None,
    vocabulary: Optional[Dict[str, Any]] = None,
    trigger_tokens: Optional[Set[str]] = None,
) -> List[dict]:
    """
    Alerts in the same domain / topic keyword thread (24h cluster window by default).
    """
    if window_hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    else:
        days = lookback_days if lookback_days is not None else 1
        since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= since,
            AlertLog.suppressed == False,  # noqa: E712
        )
        .order_by(desc(AlertLog.triggered_at), desc(AlertLog.intelligence_score))
        .limit(120)
    )
    rows = (await db.execute(stmt)).scalars().all()

    trigger_label = alert_log.target_label if alert_log else None
    trigger_topic = alert_log.topic if alert_log else None
    keywords = _topic_match_keywords(domain_id, trigger_topic, trigger_label)
    current_id = str(alert_log.id) if alert_log else None

    vocab = vocabulary or build_sector_vocabulary(
        get_pro_domain_config(domain_id) or {}, {}
    )
    t_tokens = trigger_tokens or set()

    matched: List[AlertLog] = []
    for row in rows:
        if not _alert_matches_domain_context(row, domain_id, keywords):
            continue
        label = sanitize_unicode_text(row.target_label or "")
        score = structural_correlation_score(label, vocab, trigger_tokens=t_tokens)
        if infer_domain_from_topic(row.topic or "") == domain_id:
            score = max(score, 0.55)
        if score < MIN_ALERT_CORRELATION:
            continue
        matched.append(row)

    # Ensure trigger alert is included and first in timeline ordering later
    if alert_log and all(str(a.id) != current_id for a in matched):
        matched.insert(0, alert_log)

    matched.sort(
        key=lambda a: (a.intelligence_score or 0.0, a.triggered_at or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )
    selected: List[AlertLog] = []
    if alert_log:
        selected.append(alert_log)
    for row in matched:
        if alert_log and str(row.id) == current_id:
            continue
        selected.append(row)
        if len(selected) >= limit:
            break

    events: List[dict] = []
    for row in selected:
        row_meta = row.metadata_json or {}
        events.append(
            {
                "alert_id": str(row.id),
                "title": sanitize_unicode_text((row.target_label or "")[:200]),
                "topic": row.topic,
                "severity": row.severity,
                "trigger_type": row.trigger_type,
                "timestamp": row.triggered_at.isoformat() if row.triggered_at else None,
                "source": "alert_log",
                "location_label": None,
                "source_url": _first_evidence_url(row_meta),
            }
        )

    window_label = (
        f"{window_hours}h"
        if window_hours is not None
        else f"{lookback_days or 1}d"
    )
    if not events and alert_log:
        notes.append(f"No related domain alerts in the last {window_label} besides the trigger.")
    elif len(events) < 2:
        notes.append(f"Limited related alert history in the last {window_label}.")

    return events


def _build_event_timeline(
    related_news: List[dict],
    signal_ctx: Optional[dict],
    *,
    related_events: Optional[List[dict]] = None,
    vocabulary: Optional[Dict[str, Any]] = None,
    trigger_tokens: Optional[Set[str]] = None,
) -> List[dict]:
    """
    Merge related AlertLog events and news evidence into one chronological timeline.
    """
    raw: List[dict] = []

    vocab = vocabulary or {"phrases": set(), "series_ids": set()}
    t_tokens = trigger_tokens or set()

    for ev in related_events or []:
        title = sanitize_unicode_text(ev.get("title") or "")
        coeff = structural_correlation_score(title, vocab, trigger_tokens=t_tokens)
        if ev.get("alert_id") == (signal_ctx or {}).get("alert_id"):
            coeff = max(coeff, 1.0)
        raw.append(
            {
                "timestamp": ev.get("timestamp"),
                "title": title,
                "source_url": ev.get("source_url"),
                "location_label": ev.get("location_label"),
                "alert_id": ev.get("alert_id"),
                "severity": ev.get("severity"),
                "trigger_type": ev.get("trigger_type"),
                "source": ev.get("source", "alert_log"),
                "structural_correlation": round(coeff, 3),
            }
        )

    seen_titles: Set[str] = {r["title"].lower() for r in raw if r.get("title")}

    _MARKET_KW = {"market", "stock", "etf", "bond", "yield", "price", "rally", "crash", "surge", "plunge", "trading"}
    _CONFIRM_KW = {"confirm", "verify", "report", "official", "statement", "announce"}

    for item in related_news[:5]:
        title = sanitize_unicode_text(
            (item.get("title") or item.get("headline") or item.get("text", "") or "")[:200]
        )
        coeff = structural_correlation_score(title, vocab, trigger_tokens=t_tokens)
        if coeff < MIN_NEWS_CORRELATION:
            continue
        if title.lower() in seen_titles:
            continue
        source_url = item.get("url") or item.get("source_url") or item.get("link", "")
        timestamp = item.get("published") or item.get("timestamp") or item.get("date")
        location_label = item.get("location") or item.get("country") or None
        title_lower = title.lower()
        if any(kw in title_lower for kw in _MARKET_KW):
            role = "market_reaction"
        elif any(kw in title_lower for kw in _CONFIRM_KW):
            role = "confirmation"
        else:
            role = "context"
        raw.append(
            {
                "timestamp": timestamp,
                "title": title,
                "alert_id": None,
                "source_url": (str(source_url).strip() if source_url else None) or None,
                "location_label": location_label,
                "source": "news",
                "role": role,
                "structural_correlation": round(coeff, 3),
            }
        )
        seen_titles.add(title.lower())

    def _sort_key(item: dict) -> tuple:
        ts = item.get("timestamp")
        if ts:
            return (0, str(ts))
        return (1, "")

    raw.sort(key=_sort_key)

    trigger_alert_id = (signal_ctx or {}).get("alert_id")
    typed = _assign_timeline_types(raw, trigger_alert_id)
    return filter_correlated_timeline_events(typed)


def _assign_timeline_types(timeline: List[dict], trigger_alert_id: Optional[str]) -> List[dict]:
    """Map entries to UI types: trigger, context, background."""
    if not timeline:
        return []

    for item in timeline:
        if trigger_alert_id and item.get("alert_id") == trigger_alert_id:
            item["type"] = "trigger"
            item["role"] = "trigger"
        elif item.get("role") in ("background", "trigger", "context", "market_reaction", "confirmation"):
            role = item["role"]
            if role in ("market_reaction", "confirmation"):
                item["type"] = "context"
            elif role == "background":
                item["type"] = "background"
            else:
                item["type"] = role
        else:
            item["type"] = None

    non_trigger_idxs = [
        i for i, item in enumerate(timeline) if item.get("type") not in ("trigger",)
    ]
    if not non_trigger_idxs:
        return timeline

    if len(non_trigger_idxs) == 1:
        timeline[non_trigger_idxs[0]]["type"] = "context"
        timeline[non_trigger_idxs[0]]["role"] = "context"
    else:
        first_i = non_trigger_idxs[0]
        timeline[first_i]["type"] = "background"
        timeline[first_i]["role"] = "background"
        for i in non_trigger_idxs[1:]:
            if timeline[i].get("type") is None:
                timeline[i]["type"] = "context"
                timeline[i]["role"] = "context"

    return timeline

