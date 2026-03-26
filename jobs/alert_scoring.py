import logging
from sqlalchemy.future import select
from sqlalchemy import func
from db.models import AlertLog

logger = logging.getLogger(__name__)

# Scoring Weights
WEIGHTS = {
    "intensity": 0.30,
    "spike": 0.20,
    "domains": 0.20,
    "historical": 0.30
}

# Max values for normalization
MAX_INTENSITY = 10.0
MAX_SPIKE = 5.0
MAX_DOMAINS = 10

async def calculate_alert_score(db, intensity: float, spike: float, domains: int, trigger_type: str, target_label: str) -> tuple[float, dict]:
    """
    Calculates a normalized intelligence score (0.0 - 1.0) and returns the breakdown.
    Combines direct metrics with historical performance of similar patterns.
    """
    # 1. Component Scores
    s_intensity = min(intensity / MAX_INTENSITY, 1.0)
    s_spike = min(spike / MAX_SPIKE, 1.0)
    s_domains = min(domains / MAX_DOMAINS, 1.0)
    
    # 2. Historical Reliability Score
    # Fetch average feedback for this pattern or trigger type
    stmt = select(func.avg(AlertLog.feedback_score)).where(
        AlertLog.target_label == target_label,
        AlertLog.feedback_score.isnot(None)
    )
    avg_feedback = (await db.execute(stmt)).scalar()
    
    if avg_feedback is None:
        # Fallback to trigger_type average if pattern is new
        stmt_alt = select(func.avg(AlertLog.feedback_score)).where(
            AlertLog.trigger_type == trigger_type,
            AlertLog.feedback_score.isnot(None)
        )
        avg_feedback = (await db.execute(stmt_alt)).scalar() or 3.0 # Default to neutral
    
    # Normalize feedback (1-5 scale to 0.0-1.0)
    s_historical = (avg_feedback - 1) / 4.0
    
    # 3. Final weighted score
    final_score = (
        s_intensity * WEIGHTS["intensity"] +
        s_spike * WEIGHTS["spike"] +
        s_domains * WEIGHTS["domains"] +
        s_historical * WEIGHTS["historical"]
    )
    
    breakdown = {
        "intensity_contrib": round(s_intensity * WEIGHTS["intensity"], 3),
        "spike_contrib": round(s_spike * WEIGHTS["spike"], 3),
        "domain_contrib": round(s_domains * WEIGHTS["domains"], 3),
        "historical_contrib": round(s_historical * WEIGHTS["historical"], 3),
        "raw_values": {
            "intensity": intensity,
            "spike_delta": spike,
            "domain_count": domains,
            "avg_feedback": round(float(avg_feedback), 2) if avg_feedback else None
        }
    }
    
    logger.info(f"Scored {target_label}: {final_score:.2f} (I:{breakdown['intensity_contrib']}, S:{breakdown['spike_contrib']}, D:{breakdown['domain_contrib']}, H:{breakdown['historical_contrib']})")
    
    return round(final_score, 3), breakdown

async def get_dynamic_threshold(db, trigger_type: str, severity: str) -> float:
    """
    Returns a minimum intelligence score required for an alert.
    Can be adjusted based on system load or global noise levels.
    """
    # Placeholder: In the future, this could be learned or stored in DB
    return 0.35 # Default base threshold
