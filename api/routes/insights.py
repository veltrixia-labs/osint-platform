import logging

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
from processor.topic_registry import internal_topic_for_fallback
from analysis.intensity_pressure import (
    build_domain_pressure_metrics,
    raw_intensity_from_alert,
)
from analysis.pressure_derivatives import enrich_risk_summary_with_derivatives
from analysis.lead_lag_engine import compute_lead_lag_matrix

router = APIRouter(tags=["insights"])
logger = logging.getLogger(__name__)

STRATEGIC_TOPICS = [
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
]

EMPTY_PRO_INSIGHTS: dict[str, Any] = {
    "risk_summary": {},
    "momentum_alerts": [],
    "early_warnings": [],
    "sector_distribution": {},
    "top_entities": [],
    "coverage_domains": len(STRATEGIC_TOPICS),
    "active_domains": 0,
    "focus_alert_id": None,
    # Module A — Risk Contagion Lead-Lag Tracker
    "lead_lag_matrix": [],
    # Module C — Verified Source Evidence Stream
    "evidence_stream": [],
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


def _domain_id_for_alert_topic(topic: str | None) -> str:
    """Map AlertLog.topic (strategic UPPER codes or legacy snake_case) to API domain keys."""
    return internal_topic_for_fallback(topic or "")


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
            domain = _domain_id_for_alert_topic(alert.topic)
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

    stmt_momentum = select(AlertLog).where(
        AlertLog.triggered_at >= lookback,
        AlertLog.suppressed == False,  # noqa: E712
    )
    if effective_topic:
        stmt_momentum = stmt_momentum.where(AlertLog.topic == effective_topic)
    stmt_momentum = stmt_momentum.order_by(AlertLog.intensity.desc()).limit(3)
    momentum_alerts = list((await db.execute(stmt_momentum)).scalars().all())

    if focus_alert and all(a.id != focus_alert.id for a in momentum_alerts):
        momentum_alerts = [focus_alert] + momentum_alerts[:2]

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

    # ── Module B: Momentum & Acceleration — enrich risk_summary in-place ──────
    enrich_risk_summary_with_derivatives(risk_summary)

    # ── Module A: Risk Contagion Lead-Lag Matrix ───────────────────────────────
    lead_lag_matrix = compute_lead_lag_matrix(risk_summary)

    active_domains = sum(
        1
        for t in STRATEGIC_TOPICS
        if (risk_summary.get(t) or {}).get("intensity", 0) > 0
    )

    # ── Module C: Verified Source Evidence Stream ──────────────────────────────
    # Flatten the top-5 highest-intensity alerts' evidence metadata into
    # a compact stream array for the horizontal ticker.
    stmt_evidence = (
        select(AlertLog)
        .where(
            AlertLog.triggered_at >= lookback,
            AlertLog.suppressed == False,  # noqa: E712
            AlertLog.intensity.isnot(None),
        )
        .order_by(AlertLog.intensity.desc())
        .limit(20)  # fetch extra; we filter to top 5 with evidence below
    )
    evidence_alerts_raw = list((await db.execute(stmt_evidence)).scalars().all())

    evidence_stream: list[dict[str, Any]] = []
    for a in evidence_alerts_raw:
        if len(evidence_stream) >= 5:
            break
        meta = a.metadata_json or {}
        ev_list = meta.get("evidence_list", [])
        if not ev_list:
            continue
        top_ev = ev_list[0] if ev_list else {}
        source_name = (
            top_ev.get("source")
            or top_ev.get("domain")
            or top_ev.get("type")
            or "OSINT"
        )
        display_title = (
            meta.get("display_title")
            or a.target_label
            or "Intelligence Signal"
        )
        url = top_ev.get("url") or top_ev.get("link") or None
        evidence_stream.append({
            "alert_id": str(a.id),
            "topic": a.topic or "",
            "source_name": str(source_name)[:60],
            "title": str(display_title)[:120],
            "confidence_score": round(float(a.fidelity_score or 0.0), 2),
            "url": url,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
            # Full evidence list for the modal
            "evidence_list": ev_list,
        })

    return {
        "risk_summary": risk_summary,
        "momentum_alerts": [
            {
                "id": str(a.id),
                "title": a.target_label,
                "intensity": a.intensity,
                "topic": a.topic,
            }
            for a in momentum_alerts
        ],
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
        # ── New quantitative modules ────────────────────────────────────────
        "lead_lag_matrix": lead_lag_matrix,
        "evidence_stream": evidence_stream,
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
