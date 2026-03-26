import logging
from typing import Any
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

async def calculate_alert_score(db, intensity: Any, spike: Any, domains: Any, trigger_type: str, target_label: str) -> tuple[float, dict]:
    """
    Calculates a normalized intelligence score (0.0 - 1.0) and returns the breakdown.
    Combines direct metrics with historical performance of similar patterns.
    """
    # 0. Normalize inputs at boundary for numeric safety
    # Ensure Decimal, float, int, and None are handled consistently
    try:
        f_intensity = float(intensity) if intensity is not None else 0.0
        f_spike = float(spike) if spike is not None else 0.0
        f_domains = float(domains) if domains is not None else 0.0
    except (TypeError, ValueError):
        logger.warning(f"Unexpected numeric input type for scoring: {type(intensity)}, {type(spike)}, {type(domains)}")
        f_intensity, f_spike, f_domains = 0.0, 0.0, 0.0

    # 1. Component Scores
    s_intensity = min(f_intensity / MAX_INTENSITY, 1.0)
    s_spike = min(f_spike / MAX_SPIKE, 1.0)
    s_domains = min(f_domains / MAX_DOMAINS, 1.0)
    
    # 2. Historical Reliability Score
    # Fetch average feedback for this pattern or trigger type
    stmt = select(func.avg(AlertLog.feedback_score)).where(
        AlertLog.target_label == target_label,
        AlertLog.feedback_score.isnot(None)
    )
    db_feedback = (await db.execute(stmt)).scalar()
    
    if db_feedback is None:
        # Fallback to trigger_type average if pattern is new
        stmt_alt = select(func.avg(AlertLog.feedback_score)).where(
            AlertLog.trigger_type == trigger_type,
            AlertLog.feedback_score.isnot(None)
        )
        db_feedback = (await db.execute(stmt_alt)).scalar()
    
    # Normalize feedback (1-5 scale to 0.0-1.0)
    # Convert DB Decimal to float early to avoid mixed arithmetic crashes
    avg_feedback_f = float(db_feedback) if db_feedback is not None else 3.0
    s_historical = (avg_feedback_f - 1.0) / 4.0
    
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
            "intensity": f_intensity,
            "spike_delta": f_spike,
            "domain_count": f_domains,
            "avg_feedback": round(avg_feedback_f, 2)
        }
    }
    
    logger.info(f"Scored {target_label}: {final_score:.2f} (I:{breakdown['intensity_contrib']}, S:{breakdown['spike_contrib']}, D:{breakdown['domain_contrib']}, H:{breakdown['historical_contrib']})")
    
    return round(float(final_score), 3), breakdown

async def get_dynamic_threshold(db, trigger_type: str, severity: str) -> float:
    """
    Returns a minimum intelligence score required for an alert.
    Can be adjusted based on system load or global noise levels.
    """
    # Placeholder: In the future, this could be learned or stored in DB
    return 0.35 # Default base threshold
