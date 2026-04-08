import logging
from sqlalchemy.future import select
from sqlalchemy import func
from db.models import AnalystProfile, AlertLog, AlertDelivery
from datetime import datetime, timezone, timedelta
from api.gating import get_effective_tier, TIER_FREE

logger = logging.getLogger(__name__)

# Personalization Config
MATCH_BONUS = 0.20
MAX_MULTIPLIER = 1.50
BROADCAST_SCORE_THRESHOLD = 0.85

def calculate_personal_relevance(alert_label: str, alert_metadata: dict, profile: AnalystProfile) -> float:
    """
    Calculates a personal relevance multiplier based on analyst watchlists.
    Capped at MAX_MULTIPLIER to preserve system-wide intelligence score integrity.
    """
    multiplier = 1.0
    
    # 1. Keywords Match
    if profile.watch_keywords:
        for kw in profile.watch_keywords:
            if kw.lower() in alert_label.lower():
                multiplier += MATCH_BONUS
                break # Only one match bonus per category to prevent runaway scaling
                
    # 2. Entities Match
    if profile.watch_entities:
        entities = alert_metadata.get("scoring_breakdown", {}).get("raw_values", {}).get("entities", [])
        # Also check target_label itself as it often contains the primary entity
        for ent in profile.watch_entities:
            if ent.lower() in alert_label.lower() or any(ent.lower() in e.lower() for e in entities):
                multiplier += MATCH_BONUS
                break

    # 3. Sectors/Topics Match
    if profile.watch_sectors:
        # Check if the alert relates to a sector (often implied in label or metadata)
        for sector in profile.watch_sectors:
            if sector.lower() in alert_label.lower():
                multiplier += MATCH_BONUS
                break

    final_multiplier = min(multiplier, MAX_MULTIPLIER)
    return round(final_multiplier, 2)

def should_broadcast(alert_score: float, severity: str) -> bool:
    """
    Broadcast rule: Critical alerts with very high intelligence scores 
    are delivered to all active analysts regardless of watchlists.
    """
    return severity.lower() == "critical" and alert_score >= BROADCAST_SCORE_THRESHOLD

async def get_target_analysts(db, alert_label: str, alert_score: float, severity: str, alert_metadata: dict):
    """
    Identifies which analysts should receive this alert.
    Returns a list of (profile, personalized_score, is_broadcast).
    """
    stmt = select(AnalystProfile).where(AnalystProfile.is_active == True)
    profiles = (await db.execute(stmt)).scalars().all()
    
    is_broadcast = should_broadcast(alert_score, severity)
    targets = []
    
    sev_rank = {"critical": 3, "elevated": 2, "watch": 1}
    current_sev_rank = sev_rank.get(severity.lower(), 1)

    for p in profiles:
        tier = await get_effective_tier(p)
        
        # 1. Check Broadcast Rule (Always deliver regardless of tier/limits for safety)
        if is_broadcast:
            targets.append((p, alert_score, True))
            continue
            
        # 2. Check Severity Threshold
        p_min_sev = p.min_severity_threshold.lower() if p.min_severity_threshold else "watch"
        p_sev_rank = sev_rank.get(p_min_sev, 1)
        if current_sev_rank < p_sev_rank:
            continue
            
        # 3. Check Tier Limits (Free Tier Gating)
        if tier == TIER_FREE:
            # Check 24h delivery count
            day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
            count_stmt = select(func.count(AlertDelivery.id)).where(
                AlertDelivery.analyst_id == p.id,
                AlertDelivery.delivered_at >= day_ago,
                AlertDelivery.status == "delivered"
            )
            delivered_count = (await db.execute(count_stmt)).scalar() or 0
            if delivered_count >= 5: # Free tier limit: 5 alerts/day
                continue

        # 4. Calculate Personalized Score
        rel_multiplier = calculate_personal_relevance(alert_label, alert_metadata, p)
        personal_score = min(alert_score * rel_multiplier, 1.0)
        
        # 5. Check Intelligence Threshold
        p_min_intel = p.min_intelligence_threshold if p.min_intelligence_threshold is not None else 0.0
        if personal_score >= p_min_intel:
            targets.append((p, round(personal_score, 3), False))
            
    return targets
