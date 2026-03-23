from enum import Enum

class PlanTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    EXPERTS = "experts"
    ENTERPRISE = "enterprise"

class ReportType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SYSTEM_DIAGNOSTIC = "system_diagnostic"

# Tier Hierarchy for simple comparison
TIER_ORDER = [PlanTier.FREE, PlanTier.PRO, PlanTier.EXPERTS, PlanTier.ENTERPRISE]

def is_tier_sufficient(user_tier: str, required_tier: str) -> bool:
    try:
        u_idx = TIER_ORDER.index(user_tier)
        r_idx = TIER_ORDER.index(required_tier)
        return u_idx >= r_idx
    except ValueError:
        return False
