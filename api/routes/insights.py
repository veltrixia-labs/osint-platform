from fastapi import APIRouter, Depends, Query
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, desc
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import random
from db.database import get_db
from db.models import AlertLog, TrendSignal, Stakeholder
from db.enums import PlanTier
from api.gating import requires_tier, get_effective_tier, _gate_cascading_impacts

router = APIRouter(tags=["insights"])

@router.get("/insights/pro")
async def get_pro_insights(
    topic: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.PRO.value))
):
    """
    Tier: Pro+
    Decision-Grade Summary of current risks and momentum.
    """
    user = user_data # AnalystProfile
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(hours=24)

    # 1. Momentum Alerts (Top 3 by Intensity)
    stmt_momentum = select(AlertLog).filter(AlertLog.triggered_at >= lookback)
    if topic:
        stmt_momentum = stmt_momentum.filter(AlertLog.topic == topic)
    stmt_momentum = stmt_momentum.order_by(AlertLog.intensity.desc()).limit(3)
    momentum_alerts = (await db.execute(stmt_momentum)).scalars().all()

    # 2. Early Warnings (Elevated Severity)
    stmt_warnings = select(AlertLog).filter(AlertLog.triggered_at >= lookback, AlertLog.severity == "elevated")
    if topic:
        stmt_warnings = stmt_warnings.filter(AlertLog.topic == topic)
    stmt_warnings = stmt_warnings.order_by(AlertLog.triggered_at.desc()).limit(5)
    early_warnings = (await db.execute(stmt_warnings)).scalars().all()

    # 3. Sector Distribution (Simple aggregate)
    stmt_dist合 = select(AlertLog.topic, func.count(AlertLog.id)).filter(AlertLog.triggered_at >= lookback).group_by(AlertLog.topic)
    dist_res = await db.execute(stmt_dist合)
    sector_distribution = {row[0]: row[1] for row in dist_res.all()}

    # 4. Top Entities
    ent_res = await db.execute(stmt_entities)
    top_entities = []
    for row in ent_res.all():
        top_entities.append({
            "name": row[0], 
            "count": row[1],
            "entity_comment": f"High signal cluster detected in {lookback.strftime('%m/%d')} window."
        })

    # 5. Risk Summary by strategic domains
    STRATEGIC_TOPICS = [
        "energy_resource_risk", "global_market_intelligence", "crypto_geopolitics",
        "ai_semiconductor_intelligence", "defense_technology", "supply_chain_intelligence"
    ]
    MATTER_TEMPLATES = {
        "energy_resource_risk": "Rising extraction costs in primary basins may pressure downstream manufacturing margins.",
        "global_market_intelligence": "Market volatility is decoupled from fundamentals; expect increased volume in downstream derivatives.",
        "crypto_geopolitics": "Institutional adoption is driving sovereign risk hedges, impacting fiat stability in secondary regions.",
        "ai_semiconductor_intelligence": "Export controls are tightening; expect downstream delivery delays in Tier 2 consumer foundries.",
        "defense_technology": "Rapid dual-use tech integration is shifting deterrent balances, affecting regional procurement cycles.",
        "supply_chain_intelligence": "Port congestion metrics are rising; review alternative logistics routes to mitigate downstream inventory lag."
    }
    risk_summary = {}
    for t in STRATEGIC_TOPICS:
        stmt_t = select(AlertLog).filter(AlertLog.topic == t).order_by(AlertLog.triggered_at.desc()).limit(1)
        latest = (await db.execute(stmt_t)).scalar_one_or_none()
        
        # [v16.2] Trend Calculation (vs 24h ago)
        lookback_24h = now - timedelta(hours=48)
        stmt_prev = select(AlertLog).filter(AlertLog.topic == t, AlertLog.triggered_at < lookback).order_by(AlertLog.triggered_at.desc()).limit(1)
        prev = (await db.execute(stmt_prev)).scalar_one_or_none()
        
        delta = (latest.intensity - prev.intensity) if (latest and prev) else 0.0
        
        if latest:
            risk_summary[t] = {
                "intensity": latest.intensity,
                "intensity_delta": round(delta, 1),
                "spike_detected": delta > 2.0,
                "why_it_matters": MATTER_TEMPLATES.get(t, "Sector activity indicates shifting baseline risks."),
                "top_signal": latest.target_label,
                "trend": "rising" if delta > 0.5 else "falling" if delta < -0.5 else "stable",
                "anomaly_detected": latest.intensity > 8.5,
                "anomaly_description": f"Statistical outlier detected in {t} momentum curves." if latest.intensity > 8.5 else None,
                "timestamp": latest.triggered_at.isoformat()
            }
        else:
            risk_summary[t] = {"intensity": 0.0, "intensity_delta": 0.0, "status": "no_active_signals", "why_it_matters": "No significant volatility detected in this window."}

    return {
        "risk_summary": risk_summary,
        "momentum_alerts": [
            {"id": str(a.id), "title": a.target_label, "intensity": a.intensity, "topic": a.topic} 
            for a in momentum_alerts
        ],
        "early_warnings": [
            {"id": str(a.id), "title": a.target_label, "severity": a.severity, "timestamp": a.triggered_at.isoformat()}
            for a in early_warnings
        ],
        "sector_distribution": sector_distribution,
        "top_entities": top_entities
    }

@router.get("/insights/expert")
async def get_expert_intelligence(
    db: AsyncSession = Depends(get_db),
    user_data: tuple = Depends(requires_tier(PlanTier.EXPERTS.value))
):
    """
    Tier: Expert+
    Strategic Impact Chains and Scenario Outlook.
    """
    user = user_data
    tier = await get_effective_tier(user)

    # 1. Full Impact Chains (Complete Discovery)
    stmt_impacts = select(AlertLog).filter(AlertLog.status == "confirmed").order_by(AlertLog.triggered_at.desc()).limit(10)
    alerts = (await db.execute(stmt_impacts)).scalars().all()
    
    impact_chains = []
    for a in alerts:
        impacts = a.metadata_json.get("cascading_impacts", []) if a.metadata_json else []
        gated_impacts = _gate_cascading_impacts(tier, impacts)
        if gated_impacts:
            impact_chains.append({
                "alert_id": str(a.id),
                "title": a.target_label,
                "impacts": gated_impacts
            })

    # 2. Recommended Actions & Scenario Outlook (Placeholder logic using labels/topic)
    # In production, these would be enriched by LLM in the Alert Discovery phase.
    scenarios = []
    for a in alerts[:5]:
        priority = "Critical" if a.intensity > 7.5 else "Watch" if a.intensity > 4.5 else "Low"
        
        # [v16.1] Structured Why Now Briefing: Cause -> Impact -> Pressure
        cause_map = {
            "energy_resource_risk": "Supply disruption in primary basin",
            "global_market_intelligence": "Sudden volatility spike in indexes",
            "crypto_geopolitics": "Large sovereign wallet movement",
            "default": "Systemic signal cluster detection"
        }
        impact_map = {
            "energy_resource_risk": "Downstream manufacturing cost escalation",
            "global_market_intelligence": "Liquidity crunch in secondary markets",
            "default": "Sector-wide baseline volatility increase"
        }
        
        cause = cause_map.get(a.topic, cause_map["default"])
        impact = impact_map.get(a.topic, impact_map["default"])
        pressure = "Immediate buffer reallocation required" if a.intensity > 7.0 else "Monitoring window closing"
        
        scenarios.append({
            "alert_id": str(a.id),
            "title": a.target_label,
            "priority": priority,
            "why_now": f"{cause} → {impact} → {pressure}.",
            "time_sensitivity": "IMMEDIATE" if a.intensity > 7.0 else "SHORT TERM" if a.intensity > 4.0 else "WATCH",
            "scenario_outlook": f"Critical escalation potential in {a.topic} sector.",
            "recommended_actions": [
                {"action": f"Initiate monitoring of {a.target_label} supply dependencies.", "priority": "Critical", "category": "Immediate"},
                {"action": "Review strategic inventory buffers.", "priority": priority, "category": "Monitor"}
            ]
        })

    return {
        "full_impact_chains": impact_chains,
        "scenario_outlook": scenarios,
        "cross_domain_risks": [
            # Filter findings that bridge sectors
            {"origin": a.topic, "target": "Market Stability", "intensity": 8.5} for a in alerts[:3]
        ]
    }
