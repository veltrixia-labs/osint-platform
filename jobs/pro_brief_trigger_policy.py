"""
Pro Brief Trigger Policy.

Logic for determining which AlertLog entries warrant a full Pro Structural Brief.
Ensures data density, avoids duplication, and maintains high analytical standards.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy import select, desc, or_, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AlertLog, Report
from analysis.pro_domain_config import get_pro_domain_config, infer_domain_from_topic
from analysis.pro_structural_context import build_pro_structural_context
from jobs.pro_generation_policy import (
    ALERT_CLUSTER_WINDOW_HOURS,
    PRO_DISABLE_DUPLICATE_GUARDS,
)

logger = logging.getLogger(__name__)

# Constants
ACCEPTED_SEVERITIES = ["critical", "elevated", "high"]
MIN_EVIDENCE_COUNT = 3
MIN_RELATED_NEWS_COUNT = 3
DUPLICATE_TOPIC_WINDOW_HOURS = 24
DUPLICATE_TARGET_WINDOW_HOURS = 12

def get_alert_quality_metrics(alert_log: AlertLog) -> Dict[str, Any]:
    """
    Extracts quality indicators from an alert log and its metadata.
    """
    meta = alert_log.metadata_json or {}
    
    # Evidence count can be from supporting_events_count or metadata.source_count
    evidence_count = alert_log.supporting_events_count or meta.get("source_count", 0)
    
    # Related news count from metadata
    related_news_count = meta.get("related_news_count", 0)
    
    # Domain count from metadata (multi-domain relevance)
    domain_count = meta.get("domain_count", 1)
    
    # Topic validity
    domain_id = infer_domain_from_topic(alert_log.topic)
    has_valid_topic = domain_id is not None

    return {
        "severity": alert_log.severity,
        "evidence_count": evidence_count,
        "related_news_count": related_news_count,
        "domain_count": domain_count,
        "fidelity_score": alert_log.fidelity_score,
        "is_high_fidelity": alert_log.is_high_fidelity,
        "has_valid_topic": has_valid_topic,
        "domain_id": domain_id
    }

def has_required_structural_data(context: Dict[str, Any]) -> bool:
    """
    Checks if the structural context contains meaningful baseline data.
    """
    sc = context.get("structural_context", {})
    keys_to_check = [
        "macro_observations",
        "price_pressure",
        "global_comparison",
        "trade_flows",
        "industry_stats"
    ]
    
    for key in keys_to_check:
        val = sc.get(key)
        if val:
            # If it's a list or dict, check if non-empty
            if isinstance(val, (list, dict)) and len(val) > 0:
                return True
            # If it's something else, just existence is enough
            elif not isinstance(val, (list, dict)):
                return True
    
    return False

def has_required_market_data(context: Dict[str, Any]) -> bool:
    """
    Checks if the market confirmation contains recent price action.
    """
    mc = context.get("market_confirmation", {})
    latest = mc.get("latest_prices", [])
    changes = mc.get("price_changes", {})
    
    if latest and len(latest) > 0:
        return True
    if changes and len(changes) > 0:
        return True
        
    return False

async def check_recent_duplicate_reports(
    db: AsyncSession, 
    alert_log: AlertLog, 
    domain_id: str
) -> Tuple[List[str], Dict[str, bool]]:
    """
    Legacy duplicate guard — disabled when PRO_DISABLE_DUPLICATE_GUARDS is True
    (real-time mode always INSERTs a new report).
    """
    if PRO_DISABLE_DUPLICATE_GUARDS:
        return [], {
            "duplicate_structural_brief": False,
            "duplicate_general_report": False,
        }

    reasons = []
    dup_info = {
        "duplicate_structural_brief": False,
        "duplicate_general_report": False
    }
    now = datetime.now(timezone.utc)
    
    # 1. Structural Brief Duplicate (Candidate A: Title match or report_type)
    topic_window = now - timedelta(hours=DUPLICATE_TOPIC_WINDOW_HOURS)
    stmt_structural = select(Report).where(
        Report.plan_required == "pro",
        Report.topic_code == domain_id,
        Report.created_at >= topic_window,
        or_(
            Report.report_type == "pro_structural",
            Report.title.ilike("Structural Impact Brief%")
        )
    ).limit(1)
    
    res_structural = await db.execute(stmt_structural)
    if res_structural.scalar_one_or_none():
        reasons.append(f"Recent Pro Structural Brief for domain '{domain_id}' exists (within {DUPLICATE_TOPIC_WINDOW_HOURS}h)")
        dup_info["duplicate_structural_brief"] = True

    # 2. General Pro Report Duplicate (24h)
    stmt_general = select(Report).where(
        Report.plan_required == "pro",
        Report.topic_code == domain_id,
        Report.created_at >= topic_window,
        Report.report_type != "pro_structural",
        not_(Report.title.ilike("Structural Impact Brief%"))
    ).limit(1)
    
    res_general = await db.execute(stmt_general)
    if res_general.scalar_one_or_none():
        reasons.append(f"Recent General Pro report for domain '{domain_id}' exists (within {DUPLICATE_TOPIC_WINDOW_HOURS}h)")
        dup_info["duplicate_general_report"] = True
        
    return reasons, dup_info

async def should_generate_pro_brief(
    db: AsyncSession, 
    alert_log: AlertLog
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Evaluates if an alert warrants a Pro Structural Brief.
    """
    reasons = []
    diagnostics = {
        "passed_fidelity_gate": False,
        "passed_evidence_gate": False,
        "passed_data_gate": False,
        "passed_score_gate": False,
        "duplicate_structural_brief": False,
        "duplicate_general_report": False
    }
    
    # 1. Quality Metrics
    metrics = get_alert_quality_metrics(alert_log)
    diagnostics["metrics"] = metrics
    
    if not metrics["has_valid_topic"]:
        reasons.append(f"Topic '{alert_log.topic}' does not map to a Pro domain.")
        return False, reasons, diagnostics
        
    domain_id = metrics["domain_id"]
    
    # 2. Gate Validations
    intelligence_score = alert_log.intelligence_score or 0
    fidelity_score = alert_log.fidelity_score or 0
    diagnostics["passed_fidelity_gate"] = alert_log.is_high_fidelity or fidelity_score >= 0.8
    diagnostics["passed_evidence_gate"] = metrics["evidence_count"] >= 3 or metrics["related_news_count"] >= 3
    diagnostics["passed_score_gate"] = intelligence_score >= 0.35
    
    # 3. Severity Check (Classical)
    is_classical_candidate = alert_log.severity.lower() in ACCEPTED_SEVERITIES or intelligence_score >= 0.8
    
    # 4. Data Availability Check (Lightweight Context Build)
    has_structural = False
    has_market = False
    try:
        context = await build_pro_structural_context(
            db, 
            alert_log=alert_log, 
            domain_id=domain_id
        )
        has_structural = has_required_structural_data(context)
        has_market = has_required_market_data(context)
    except Exception as e:
        logger.error(f"Error checking data availability: {e}")
        reasons.append(f"Technical error during context validation: {str(e)}")

    diagnostics["has_structural"] = has_structural
    diagnostics["has_market"] = has_market
    # Real-time mode: macro OR market is enough to keep the stream alive
    if PRO_DISABLE_DUPLICATE_GUARDS:
        diagnostics["passed_data_gate"] = has_structural or has_market
    else:
        diagnostics["passed_data_gate"] = has_structural and has_market

    # 5. Duplicate Check (Move up to use in relaxed gate criteria)
    dup_reasons, dup_info = await check_recent_duplicate_reports(db, alert_log, domain_id)
    diagnostics.update(dup_info)
    is_duplicate = dup_info["duplicate_structural_brief"]

    # 6. Combined Logic for relaxed candidacy
    is_standard_relaxed_watch = (
        alert_log.severity.lower() == "watch" and
        diagnostics["passed_fidelity_gate"] and
        diagnostics["passed_evidence_gate"] and
        diagnostics["passed_data_gate"] and
        diagnostics["passed_score_gate"] and
        not is_duplicate
    )

    # 7. Global Market Intelligence Relaxed Gate (Experimental Rescue)
    passed_gm_relaxed = (
        domain_id == "global_market_intelligence" and
        fidelity_score >= 0.6 and
        (metrics["evidence_count"] >= 4 or metrics["related_news_count"] >= 4) and
        has_structural and
        has_market and
        intelligence_score >= 0.3 and
        not is_duplicate
    )
    diagnostics["passed_global_market_relaxed_gate"] = passed_gm_relaxed
    
    is_relaxed_watch_candidate = is_standard_relaxed_watch or passed_gm_relaxed
    
    if passed_gm_relaxed:
        diagnostics["relaxed_gate_reason"] = "Global Market rescue: Evidence 4+ and Fidelity 0.6+"
        if not is_standard_relaxed_watch:
            # Explicitly mark as promoted by relaxed gate in reasons if it wouldn't have passed otherwise
            # Note: We'll add this to reasons below if it's the primary path
            pass

    if not is_classical_candidate and not is_relaxed_watch_candidate:
        if alert_log.severity.lower() in ACCEPTED_SEVERITIES:
            reasons.append("High severity but failed quality gates.")
        else:
            reasons.append("Insufficient score/severity and did not meet relaxed quality gates.")

    if not has_structural:
        reasons.append("Missing required structural baseline data (FRED/BLS/etc.)")
    if not has_market:
        reasons.append("Missing required market confirmation data (Prices/ETFs)")

    # 8. Final Duplicate Blocker check
    if is_duplicate:
        reasons.extend(dup_reasons)

    # 9. Special Reason for Relaxed Gate Promotion
    if passed_gm_relaxed and not is_classical_candidate and not is_duplicate and (has_structural and has_market):
        reasons.append("Promoted via Global Market relaxed gate (Experimental)")

    # 10. Final Decision
    # Blockers are reasons that are NOT informational promotion messages
    blockers = [r for r in reasons if "Promoted" not in r]
    should_gen = len(blockers) == 0
    
    return should_gen, reasons, diagnostics

async def select_candidate_alerts_for_pro_briefs(
    db: AsyncSession, 
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Scans recent alerts and selects the best candidates for Pro Structural Briefs.
    """
    # 24h clustering window — freshest alert context first (Context Briefs parity)
    since = datetime.now(timezone.utc) - timedelta(hours=ALERT_CLUSTER_WINDOW_HOURS)
    stmt = select(AlertLog).where(
        AlertLog.suppressed == False,
        AlertLog.triggered_at >= since,
    ).order_by(desc(AlertLog.triggered_at), desc(AlertLog.intelligence_score)).limit(80)
    
    result = await db.execute(stmt)
    alerts = result.scalars().all()
    
    candidates = []
    for alert in alerts:
        should_gen, reasons, diag = await should_generate_pro_brief(db, alert)
        
        if should_gen:
            # Simple Scoring
            # Base: intelligence_score * 100
            # Bonus: High fidelity (+20)
            # Bonus: Evidence density (+5 per source above min)
            score = (alert.intelligence_score or 0.5) * 100
            if alert.is_high_fidelity:
                score += 20
            
            metrics = diag.get("metrics", {})
            evidence_bonus = max(0, metrics.get("evidence_count", 0) - MIN_EVIDENCE_COUNT) * 5
            score += evidence_bonus
            
            candidates.append({
                "alert_id": str(alert.id),
                "topic": alert.topic,
                "target_label": alert.target_label,
                "score": round(score, 2),
                "reasons": reasons,
                "diagnostics": diag,
                "triggered_at": alert.triggered_at.isoformat()
            })
            
    # Sort by score and limit
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]
