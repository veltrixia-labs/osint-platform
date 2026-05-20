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

router = APIRouter(tags=["insights"])

STRATEGIC_TOPICS = [
    "energy_resource_risk",
    "global_market_intelligence",
    "crypto_geopolitics",
    "ai_semiconductor_intelligence",
    "defense_technology",
    "supply_chain_intelligence",
]

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


async def _build_risk_summary(
    db: AsyncSession,
    now: datetime,
    lookback: datetime,
) -> dict[str, Any]:
    risk_summary: dict[str, Any] = {}
    for t in STRATEGIC_TOPICS:
        stmt_t = (
            select(AlertLog)
            .where(AlertLog.topic == t)
            .order_by(AlertLog.triggered_at.desc())
            .limit(1)
        )
        latest = (await db.execute(stmt_t)).scalar_one_or_none()

        stmt_prev = (
            select(AlertLog)
            .where(AlertLog.topic == t, AlertLog.triggered_at < lookback)
            .order_by(AlertLog.triggered_at.desc())
            .limit(1)
        )
        prev = (await db.execute(stmt_prev)).scalar_one_or_none()

        delta = (latest.intensity - prev.intensity) if (latest and prev) else 0.0

        if latest:
            risk_summary[t] = {
                "intensity": latest.intensity,
                "intensity_delta": round(delta, 1),
                "spike_detected": delta > 2.0,
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
                "anomaly_detected": latest.intensity > 8.5,
                "anomaly_description": (
                    f"Statistical outlier detected in {t} momentum curves."
                    if latest.intensity > 8.5
                    else None
                ),
                "timestamp": latest.triggered_at.isoformat(),
            }
        else:
            risk_summary[t] = {
                "intensity": 0.0,
                "intensity_delta": 0.0,
                "status": "no_active_signals",
                "why_it_matters": "No significant volatility detected in this window.",
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
    sector_distribution = {row[0]: row[1] for row in dist_res.all()}

    top_entities = await _fetch_top_entities(
        db, lookback, topic=effective_topic, limit=10
    )
    risk_summary = await _build_risk_summary(db, now, lookback)

    active_domains = sum(
        1
        for t in STRATEGIC_TOPICS
        if (risk_summary.get(t) or {}).get("intensity", 0) > 0
    )

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
    return await build_pro_insights_payload(db, topic=topic)


@router.get("/alerts/{alert_id}/insights/pro")
async def get_pro_insights_for_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value)),
):
    """Tier: Pro+ — insights scoped to a single alert's topic and signal."""
    _ = user_data
    alert = await _load_alert_or_404(db, alert_id)
    return await build_pro_insights_payload(db, focus_alert=alert)


@router.get("/insights/expert")
async def get_expert_intelligence(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.EXPERTS.value)),
):
    """Tier: Expert+ — strategic impact chains and scenario outlook."""
    user = user_data
    tier = await get_effective_tier(user)
    return await build_expert_intelligence_payload(db, tier=tier)


@router.get("/alerts/{alert_id}/insights/expert")
async def get_expert_intelligence_for_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.EXPERTS.value)),
):
    """Tier: Expert+ — intelligence focused on one alert's impact chain."""
    user = user_data
    tier = await get_effective_tier(user)
    alert = await _load_alert_or_404(db, alert_id)
    return await build_expert_intelligence_payload(db, focus_alert=alert, tier=tier)
