import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import uuid

from db.database import get_db
from db.models import AlertLog
from db.enums import PlanTier
from api.gating import requires_tier, get_effective_tier, _gate_cascading_impacts
from processor.topic_registry import STRATEGIC_TO_INTERNAL, INTERNAL_TO_STRATEGIC
from analysis.intensity_pressure import (
    build_domain_pressure_metrics,
    raw_intensity_from_alert,
)
from analysis.lead_lag_engine import compute_lead_lag_matrix
from analysis.pro_domain_config import STRATEGIC_DOMAINS, infer_domain_from_topic

router = APIRouter(tags=["insights"])
logger = logging.getLogger(__name__)

# Canonical 6-domain list — single source of truth lives in
# `analysis.pro_domain_config.STRATEGIC_DOMAINS`. Bucketing here MUST use
# `infer_domain_from_topic` to stay aligned with the Lead-Lag engine.
STRATEGIC_TOPICS = STRATEGIC_DOMAINS

EMPTY_PRO_INSIGHTS: dict[str, Any] = {
    "risk_summary": {},
    "early_warnings": [],
    "sector_distribution": {},
    "top_entities": [],
    "coverage_domains": len(STRATEGIC_TOPICS),
    "active_domains": 0,
    "focus_alert_id": None,
    # Module A — Risk Contagion Lead-Lag Tracker
    "lead_lag_matrix": [],
}

EMPTY_EXPERT_INTEL: dict[str, Any] = {
    "full_impact_chains": [],
    "scenario_outlook": [],
    "cross_domain_risks": [],
    "counterfactuals": [],
    "tail_risks": [],
    "adversarial_take": "",
    "confidence_score": 0.0,
    "focus_alert_id": None,
}

MATTER_TEMPLATES = {
    "energy_resource_risk": "Rising extraction costs in primary basins may pressure downstream manufacturing margins.",
    "global_market_intelligence": "Market volatility is decoupled from fundamentals; expect increased volume in downstream derivatives.",
    "crypto_geopolitics": "Institutional adoption is driving sovereign risk hedges, impacting fiat stability in secondary regions.",
    "ai_semiconductor_intelligence": "Export controls are tightening; expect downstream delivery delays in Tier 2 consumer foundries.",
    "defense_technology": "Rapid dual-use tech integration is shifting deterrent balances, affecting regional procurement cycles.",
    "supply_chain_intelligence": "Port congestion metrics are rising; review alternative logistics routes to mitigate downstream inventory lag.",
}


async def _fetch_top_entities(
    db: AsyncSession,
    lookback: datetime,
    *,
    topic: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Top alert target labels in the lookback window (proxy for entity heat)."""
    stmt_entities = (
        select(AlertLog.target_label, func.count(AlertLog.id))
        .where(
            AlertLog.triggered_at >= lookback,
            AlertLog.suppressed == False,  # noqa: E712
            AlertLog.target_label.isnot(None),
            AlertLog.target_label != "",
        )
        .group_by(AlertLog.target_label)
        .order_by(desc(func.count(AlertLog.id)))
        .limit(limit)
    )
    if topic:
        stmt_entities = stmt_entities.where(AlertLog.topic == topic)

    ent_res = await db.execute(stmt_entities)
    top_entities = []
    for row in ent_res.all():
        label = row[0] or "Unknown"
        count = int(row[1] or 0)
        top_entities.append(
            {
                "name": label,
                "count": count,
                "entity_comment": f"{count} alert(s) in the last 24h window.",
            }
        )
    return top_entities


def _domain_id_for_alert_topic(topic: str | None, text: str = "") -> str:
    """
    Map AlertLog.topic to a canonical strategic domain ID.

    Delegates to `infer_domain_from_topic` (passing the headline so the sports/
    entertainment guardrail can intercept noise) — keeping this module's bucketing
    aligned with the Lead-Lag engine + Trend Flow. Sports items land in the
    non-strategic bucket and are dropped from the 6-domain risk summary.
    """
    return infer_domain_from_topic(topic or "", text=text)


async def _build_risk_summary(
    db: AsyncSession,
    now: datetime,
    lookback: datetime,
) -> dict[str, Any]:
    prev_lookback = lookback - timedelta(hours=24)

    stmt_recent = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= lookback,
            AlertLog.suppressed == False,  # noqa: E712
        )
        .order_by(desc(AlertLog.triggered_at))
    )
    stmt_prev = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= prev_lookback,
            AlertLog.triggered_at < lookback,
            AlertLog.suppressed == False,  # noqa: E712
        )
        .order_by(desc(AlertLog.triggered_at))
    )
    recent_alerts = list((await db.execute(stmt_recent)).scalars().all())
    prev_alerts = list((await db.execute(stmt_prev)).scalars().all())

    def _bucket(alerts: list[AlertLog]) -> dict[str, list[AlertLog]]:
        buckets: dict[str, list[AlertLog]] = {t: [] for t in STRATEGIC_TOPICS}
        for alert in alerts:
            domain = _domain_id_for_alert_topic(alert.topic, alert.target_label or "")
            if domain in buckets:
                buckets[domain].append(alert)
        return buckets

    recent_by_domain = _bucket(recent_alerts)
    prev_by_domain = _bucket(prev_alerts)

    risk_summary: dict[str, Any] = {}
    for t in STRATEGIC_TOPICS:
        domain_recent = recent_by_domain[t]
        if not domain_recent:
            risk_summary[t] = {
                "intensity": 0.0,
                "intensity_delta": 0.0,
                "status": "no_active_signals",
                "why_it_matters": "No significant volatility detected in this window.",
            }
            continue

        latest = max(
            domain_recent,
            key=lambda a: (
                raw_intensity_from_alert(a),
                a.triggered_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
        )
        pressure = build_domain_pressure_metrics(
            domain_recent,
            prev_by_domain[t],
            now,
        )
        delta = float(pressure.get("intensity_delta", 0.0))

        risk_summary[t] = {
            **pressure,
            "why_it_matters": MATTER_TEMPLATES.get(
                t, "Sector activity indicates shifting baseline risks."
            ),
            "top_signal": latest.target_label,
            "trend": (
                "rising"
                if delta > 0.5
                else "falling"
                if delta < -0.5
                else "stable"
            ),
            "timestamp": (
                latest.triggered_at.isoformat() if latest.triggered_at else None
            ),
            "intelligence_score": latest.intelligence_score,
        }
    return risk_summary


async def build_pro_insights_payload(
    db: AsyncSession,
    *,
    topic: Optional[str] = None,
    focus_alert: Optional[AlertLog] = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)
    effective_topic = topic or (focus_alert.topic if focus_alert else None)

    stmt_warnings = select(AlertLog).where(
        AlertLog.triggered_at >= lookback,
        AlertLog.severity == "elevated",
        AlertLog.suppressed == False,  # noqa: E712
    )
    if effective_topic:
        stmt_warnings = stmt_warnings.where(AlertLog.topic == effective_topic)
    stmt_warnings = stmt_warnings.order_by(AlertLog.triggered_at.desc()).limit(5)
    early_warnings = (await db.execute(stmt_warnings)).scalars().all()

    stmt_dist = (
        select(AlertLog.topic, func.count(AlertLog.id))
        .where(AlertLog.triggered_at >= lookback, AlertLog.suppressed == False)  # noqa: E712
        .group_by(AlertLog.topic)
    )
    if effective_topic:
        stmt_dist = stmt_dist.where(AlertLog.topic == effective_topic)
    dist_res = await db.execute(stmt_dist)
    sector_distribution: dict[str, int] = {t: 0 for t in STRATEGIC_TOPICS}
    for row in dist_res.all():
        domain = _domain_id_for_alert_topic(row[0])
        if domain in sector_distribution:
            sector_distribution[domain] += int(row[1] or 0)

    top_entities = await _fetch_top_entities(
        db, lookback, topic=effective_topic, limit=10
    )
    risk_summary = await _build_risk_summary(db, now, lookback)

    # ── Module A: Risk Contagion Lead-Lag Matrix ───────────────────────────────
    if os.getenv("ENABLE_LEADLAG", "false").lower() == "true":
        lead_lag_matrix = await compute_lead_lag_matrix(db)
    else:
        lead_lag_matrix = []

    active_domains = sum(
        1
        for t in STRATEGIC_TOPICS
        if (risk_summary.get(t) or {}).get("intensity", 0) > 0
    )

    return {
        "risk_summary": risk_summary,
        "early_warnings": [
            {
                "id": str(a.id),
                "title": a.target_label,
                "severity": a.severity,
                "timestamp": a.triggered_at.isoformat(),
            }
            for a in early_warnings
        ],
        "sector_distribution": sector_distribution,
        "top_entities": top_entities,
        "coverage_domains": len(STRATEGIC_TOPICS),
        "active_domains": active_domains,
        "focus_alert_id": str(focus_alert.id) if focus_alert else None,
        "lead_lag_matrix": lead_lag_matrix,
    }


async def build_drilldown_payload(db: AsyncSession, topic: str) -> dict[str, Any]:
    """Fetches rich entity and trigger news data for a specific sector over a 72h window.
    
    `topic` may be either snake_case (energy_resource_risk) or DB UPPER code (ENERGY).
    We normalise to DB UPPER codes for the query.
    """
    # Resolve to DB canonical UPPER code (e.g. 'energy_resource_risk' → 'ENERGY')
    upper = topic.strip().upper().replace('-', '_')
    if upper in STRATEGIC_TO_INTERNAL:         # already a canonical code
        db_topic = upper
    elif topic.lower() in INTERNAL_TO_STRATEGIC:  # snake_case internal code
        db_topic = INTERNAL_TO_STRATEGIC[topic.lower()]
    else:
        db_topic = upper  # fallback
    
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=72)

    # 1. Top Entities — deduplicate and count by target_label
    stmt_ent = (
        select(
            AlertLog.target_label,
            func.count(AlertLog.id).label("alert_count"),
            func.max(AlertLog.intensity).label("max_intensity"),
            func.max(AlertLog.severity).label("top_severity"),
        )
        .where(
            AlertLog.topic == db_topic,
            AlertLog.triggered_at >= lookback,
            AlertLog.suppressed == False,
            AlertLog.target_label.isnot(None),
            AlertLog.target_label != "",
        )
        .group_by(AlertLog.target_label)
        .order_by(desc(func.count(AlertLog.id)), desc(func.max(AlertLog.intensity)))
        .limit(10)
    )
    ent_res = await db.execute(stmt_ent)
    top_entities = [
        {
            "name": row[0],
            "count": int(row[1] or 0),
            "max_intensity": round(float(row[2] or 0.0), 1),
            "severity": row[3] or "watch",
        }
        for row in ent_res.all()
    ]

    # 2. Trigger News — get highest intensity alerts with full evidence
    stmt_news = (
        select(AlertLog)
        .where(
            AlertLog.topic == db_topic,
            AlertLog.triggered_at >= lookback,
            AlertLog.suppressed == False,
        )
        .order_by(desc(AlertLog.intensity))
        .limit(15)  # fetch extra to find those with good evidence
    )
    news_res = await db.execute(stmt_news)
    news_alerts = list(news_res.scalars().all())

    trigger_news = []
    seen_titles: set[str] = set()
    for a in news_alerts:
        if len(trigger_news) >= 8:
            break
        meta = a.metadata_json or {}
        ev_list = meta.get("evidence_list", [])

        # Prefer first piece of evidence that has a URL
        top_ev = next((e for e in ev_list if e.get("url") or e.get("link")), ev_list[0] if ev_list else {})

        display_title = (
            meta.get("display_title")
            or a.target_label
            or "Intelligence Signal"
        )
        # Deduplicate by title
        title_key = display_title[:80].lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        source_name = (
            top_ev.get("source")
            or top_ev.get("domain")
            or meta.get("source_name", "OSINT Stream")
        )
        url = top_ev.get("url") or top_ev.get("link") or None
        article_title = top_ev.get("title") or display_title

        trigger_news.append({
            "id": str(a.id),
            "headline": str(article_title)[:160],
            "display_title": str(display_title)[:120],
            "intensity": round(float(a.intensity or 0), 1),
            "severity": a.severity or "watch",
            "fidelity_score": round(float(a.fidelity_score or 0.0), 2),
            "timestamp": a.triggered_at.isoformat() if a.triggered_at else None,
            "source": str(source_name)[:60],
            "url": url,
            "trigger_type": a.trigger_type or "signal",
            "supporting_sources_count": len(ev_list),
        })

    # 3. Sector stats summary
    stmt_stats = (
        select(
            func.count(AlertLog.id).label("total_alerts"),
            func.avg(AlertLog.intensity).label("avg_intensity"),
            func.max(AlertLog.intensity).label("peak_intensity"),
        )
        .where(
            AlertLog.topic == db_topic,
            AlertLog.triggered_at >= lookback,
            AlertLog.suppressed == False,
        )
    )
    stats_res = await db.execute(stmt_stats)
    stats_row = stats_res.one()
    sector_stats = {
        "total_alerts": int(stats_row[0] or 0),
        "avg_intensity": round(float(stats_row[1] or 0.0), 1),
        "peak_intensity": round(float(stats_row[2] or 0.0), 1),
        "window_hours": 72,
    }

    return {
        "topic": topic,
        "top_entities": top_entities,
        "trigger_news": trigger_news,
        "sector_stats": sector_stats,
    }


async def build_expert_intelligence_payload(
    db: AsyncSession,
    *,
    focus_alert: Optional[AlertLog] = None,
    tier: str = PlanTier.EXPERTS.value,
) -> dict[str, Any]:
    stmt_impacts = (
        select(AlertLog)
        .where(AlertLog.status == "confirmed", AlertLog.suppressed == False)  # noqa: E712
        .order_by(AlertLog.triggered_at.desc())
        .limit(10)
    )
    if focus_alert:
        stmt_impacts = select(AlertLog).where(AlertLog.id == focus_alert.id)
    alerts = list((await db.execute(stmt_impacts)).scalars().all())

    impact_chains = []
    for a in alerts:
        impacts = a.metadata_json.get("cascading_impacts", []) if a.metadata_json else []
        gated_impacts = _gate_cascading_impacts(tier, impacts)
        if gated_impacts:
            impact_chains.append(
                {
                    "alert_id": str(a.id),
                    "title": a.target_label,
                    "impacts": gated_impacts,
                }
            )

    scenarios = []
    for a in alerts[:5]:
        priority = (
            "Critical"
            if a.intensity > 7.5
            else "Watch"
            if a.intensity > 4.5
            else "Low"
        )
        cause_map = {
            "energy_resource_risk": "Supply disruption in primary basin",
            "global_market_intelligence": "Sudden volatility spike in indexes",
            "crypto_geopolitics": "Large sovereign wallet movement",
            "default": "Systemic signal cluster detection",
        }
        impact_map = {
            "energy_resource_risk": "Downstream manufacturing cost escalation",
            "global_market_intelligence": "Liquidity crunch in secondary markets",
            "default": "Sector-wide baseline volatility increase",
        }
        cause = cause_map.get(a.topic, cause_map["default"])
        impact = impact_map.get(a.topic, impact_map["default"])
        pressure = (
            "Immediate buffer reallocation required"
            if a.intensity > 7.0
            else "Monitoring window closing"
        )
        scenarios.append(
            {
                "alert_id": str(a.id),
                "title": a.target_label,
                "priority": priority,
                "why_now": f"{cause} → {impact} → {pressure}.",
                "time_sensitivity": (
                    "IMMEDIATE"
                    if a.intensity > 7.0
                    else "SHORT TERM"
                    if a.intensity > 4.0
                    else "WATCH"
                ),
                "scenario_outlook": f"Critical escalation potential in {a.topic} sector.",
                "recommended_actions": [
                    {
                        "action": f"Initiate monitoring of {a.target_label} supply dependencies.",
                        "priority": "Critical",
                        "category": "Immediate",
                    },
                    {
                        "action": "Review strategic inventory buffers.",
                        "priority": priority,
                        "category": "Monitor",
                    },
                ],
            }
        )

    return {
        "full_impact_chains": impact_chains,
        "scenario_outlook": scenarios,
        "cross_domain_risks": [
            {"origin": a.topic, "target": "Market Stability", "intensity": 8.5}
            for a in alerts[:3]
        ],
        "counterfactuals": [],
        "tail_risks": [],
        "adversarial_take": "",
        "confidence_score": 0.0,
        "focus_alert_id": str(focus_alert.id) if focus_alert else None,
    }


async def _load_alert_or_404(db: AsyncSession, alert_id: uuid.UUID) -> AlertLog:
    stmt = select(AlertLog).where(AlertLog.id == alert_id)
    alert = (await db.execute(stmt)).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/insights/pro")
async def get_pro_insights(
    topic: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """Tier: Pro+ — decision-grade summary of current risks and momentum."""
    _ = user_data
    try:
        return await build_pro_insights_payload(db, topic=topic)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Alert fetch failed (get_pro_insights): %s", e, exc_info=True)
        return dict(EMPTY_PRO_INSIGHTS)


@router.get("/insights/pro/drilldown")
async def get_pro_drilldown(
    topic: str,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """Tier: Pro+ — specific deep-dive data for the radial network."""
    _ = user_data
    try:
        if not topic:
            raise HTTPException(status_code=400, detail="Topic required")
        return await build_drilldown_payload(db, topic=topic)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Drilldown fetch failed: %s", e, exc_info=True)
        return {"topic": topic, "top_entities": [], "trigger_news": []}


@router.get("/alerts/{alert_id}/insights/pro")
async def get_pro_insights_for_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """Tier: Pro+ — insights scoped to a single alert's topic and signal."""
    _ = user_data
    try:
        alert = await _load_alert_or_404(db, alert_id)
        return await build_pro_insights_payload(db, focus_alert=alert)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Alert fetch failed (get_pro_insights_for_alert): %s", e, exc_info=True)
        return dict(EMPTY_PRO_INSIGHTS)


@router.get("/insights/expert")
async def get_expert_intelligence(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.EXPERTS.value)),
):
    """Tier: Expert+ — strategic impact chains and scenario outlook."""
    user = user_data
    tier = await get_effective_tier(user)
    try:
        return await build_expert_intelligence_payload(db, tier=tier)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Alert fetch failed (get_expert_intelligence): %s", e, exc_info=True)
        return dict(EMPTY_EXPERT_INTEL)


@router.get("/alerts/{alert_id}/insights/expert")
async def get_expert_intelligence_for_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.EXPERTS.value)),
):
    """Tier: Expert+ — intelligence focused on one alert's impact chain."""
    user = user_data
    tier = await get_effective_tier(user)
    try:
        alert = await _load_alert_or_404(db, alert_id)
        return await build_expert_intelligence_payload(db, focus_alert=alert, tier=tier)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Alert fetch failed (get_expert_intelligence_for_alert): %s", e, exc_info=True)
        return dict(EMPTY_EXPERT_INTEL)

@router.get("/insights/macro-transmission")
async def get_macro_transmission(
    source: str = "DCOILWTICO",
    macro_ticker: Optional[str] = None,
    target_topic: str = "supply_chain_intelligence",
    include_inverse: bool = False,
    db: AsyncSession = Depends(get_db),
    # Use pro tier gating since this is an advanced insight
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """Tier: Pro+ — quantitative macro transmission lag and correlation.

    The macro series can be specified as either ``macro_ticker`` (preferred,
    matches the Dynamic Macro Selector wording) or ``source`` (backward-compat
    alias kept for the original WTI-only callers). When both are supplied,
    ``macro_ticker`` wins.

    Set ``include_inverse=true`` to also scan negative lags, where the alert
    intensity leads the macro asset (markets repricing after a shock).
    """
    _ = user_data
    from analysis.macro_transmission import MacroTransmissionEngine, UnknownMacroSeriesError
    chosen_ticker = (macro_ticker or source or "").strip()
    if not chosen_ticker:
        raise HTTPException(status_code=400, detail="macro_ticker (or source) is required")
    try:
        engine = MacroTransmissionEngine(db)
        return await engine.compute_transmission_metrics(
            macro_series_id=chosen_ticker,
            target_topic=target_topic,
            days_lookback=90,
            roc_window=7,
            include_inverse=include_inverse,
        )
    except UnknownMacroSeriesError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Macro transmission engine failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing transmission metrics")


@router.get("/insights/market-entropy")
async def get_market_entropy(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.FREE.value)),
):
    """
    Tier: Free — public Alert Stream / MTF surface (statistical-mechanics market entropy gauge).

    Returns a normalised entropy in [0, 1] combining topic dispersion (60%)
    and intensity dispersion (40%) over the last 24h cluster window.
    A value above the engine's BREAKOUT_THRESHOLD triggers a warning state.
    """
    _ = user_data
    from analysis.market_entropy import compute_market_entropy
    try:
        return await compute_market_entropy(db)
    except Exception as e:
        logger.error("Market entropy engine failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing market entropy")


@router.get("/insights/choke-points")
async def get_choke_points(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """
    Tier: Pro+ — Fluid Dynamics choke-point analysis.

    Returns six maritime nodes (Hormuz, Malacca, Suez, Bab-el-Mandeb, Panama,
    Bosphorus) with current OSINT viscosity, restriction factor, and
    downstream sector drag projections.
    """
    _ = user_data
    from analysis.choke_point_flow import compute_choke_point_flow
    try:
        return await compute_choke_point_flow(db)
    except Exception as e:
        logger.error("Choke-point engine failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing choke-point flow")


@router.get("/insights/hidden-accumulation")
async def get_hidden_accumulation(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """
    Tier: Pro+ — Price-OSINT divergence with CFTC overlay.

    Strict guardrails (un-loosenable):
      • cluster window = 24h
      • intensity reignite ≥ 1.5x prior peak
      • baseline intensity ≥ 1.0 (noise floor)
      • 24h macro price change ≥ 0% (flat or up)
    """
    _ = user_data
    from analysis.price_osint_divergence import detect_hidden_accumulation
    try:
        return await detect_hidden_accumulation(db)
    except Exception as e:
        logger.error("Hidden accumulation engine failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing hidden accumulation")


@router.get("/insights/sanctions-network")
async def get_sanctions_network(
    root_entity_id: Optional[str] = None,
    max_nodes: int = 60,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """
    Tier: Pro+ — Collateral Damage Network drill-down.

    Without ``root_entity_id`` returns the global ego-subgraph anchored on the
    set of sanctioned entities. With one, returns the 2-hop neighbourhood of
    that specific Stakeholder.

    Tier classification per node:
      primary | direct_collateral | indirect_collateral | background
    """
    _ = user_data
    from analysis.sanctions_network import expand_collateral_subgraph
    try:
        return await expand_collateral_subgraph(
            db, root_entity_id=root_entity_id, max_nodes=max(1, min(max_nodes, 200))
        )
    except Exception as e:
        logger.error("Sanctions network engine failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing sanctions network")


@router.get("/insights/macro-regime")
async def get_macro_regime(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """
    Tier: Pro+ — current Market Regime classification.

    Rule-based decision tree over 30-day RoC of DGS10, DCOILWTICO, VIXCLS.
    See `analysis.market_regime` for the math.
    """
    _ = user_data
    from analysis.market_regime import compute_market_regime
    try:
        return await compute_market_regime(db)
    except Exception as e:
        logger.error("Market regime engine failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing market regime")


@router.get("/insights/macro-matrix")
async def get_macro_matrix(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """
    Tier: Pro+ — full cross-sectional correlation matrix.

    Returns the Pearson correlation (peak over 0-7 day lag) for every
    (tradeable macro × strategic topic) pair. Computed in two batched DB
    queries regardless of matrix size — safe for interactive use.
    """
    _ = user_data
    from analysis.macro_transmission import MacroTransmissionEngine
    try:
        engine = MacroTransmissionEngine(db)
        return await engine.compute_correlation_matrix()
    except Exception as e:
        logger.error("Macro matrix engine failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Error computing macro matrix")


@router.get("/insights/macro-transmission/options")
async def get_macro_transmission_options(
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """
    Returns the catalog of tradeable macro series + selectable target topics
    used to populate the Dynamic Macro Selector dropdowns. The frontend treats
    this as the single source of truth — no hardcoded option lists.
    """
    _ = user_data
    from data_sources.fred_series_catalog import get_tradeable_macro_series

    # Domain → display metadata mirrors the SOURCE_META structure on the
    # frontend; centralising it here means future catalog edits never need a
    # parallel UI deploy.
    target_topics = [
        {"id": "energy_resource_risk",          "label": "Energy & Resource Risk",
         "description": "Energy supply disruption, refinery utilisation, OPEC dynamics.",
         "accent_color": "#eab308", "glow_color": "rgba(234,179,8,0.45)"},
        {"id": "global_market_intelligence",    "label": "Global Market Intelligence",
         "description": "Macro policy, rate cycles, cross-asset risk repricing.",
         "accent_color": "#58a6ff", "glow_color": "rgba(88,166,255,0.45)"},
        {"id": "ai_semiconductor_intelligence", "label": "AI & Semiconductor",
         "description": "Foundry concentration, export controls, AI capex.",
         "accent_color": "#bc8cff", "glow_color": "rgba(188,140,255,0.45)"},
        {"id": "supply_chain_intelligence",     "label": "Supply Chain Intelligence",
         "description": "Logistics bottlenecks, freight rates, critical-material flows.",
         "accent_color": "#10b981", "glow_color": "rgba(16,185,129,0.45)"},
        {"id": "defense_technology",            "label": "Defense Technology",
         "description": "Procurement cycles, FMS approvals, critical materials.",
         "accent_color": "#f87171", "glow_color": "rgba(248,113,113,0.40)"},
        {"id": "crypto_geopolitics",            "label": "Crypto Geopolitics",
         "description": "Digital asset adoption, monetary sovereignty, sanctions vectors.",
         "accent_color": "#f59e0b", "glow_color": "rgba(245,158,11,0.45)"},
    ]

    macro_series = []
    for s in get_tradeable_macro_series():
        macro_series.append({
            "id": s["series_id"],
            "label": s.get("display_label") or s["series_id"],
            "name": s.get("name"),
            "category": s.get("category"),
            "frequency": s.get("frequency_hint"),
            "unit_label": s.get("transmission_unit_label") or s.get("unit"),
            "accent_color": s.get("accent_color") or "#94a3b8",
            "provider": "FRED",
        })

    return {
        "macro_series": macro_series,
        "target_topics": target_topics,
        "defaults": {
            "macro_ticker": "DCOILWTICO",
            "target_topic": "supply_chain_intelligence",
        },
    }

