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
    """Check if the user_tier meets or exceeds the required_tier."""
    try:
        # Resolve string values to enum instances
        u_tier = user_tier if isinstance(user_tier, PlanTier) else PlanTier(user_tier)
        r_tier = required_tier if isinstance(required_tier, PlanTier) else PlanTier(required_tier)
        return TIER_ORDER.index(u_tier) >= TIER_ORDER.index(r_tier)
    except (ValueError, KeyError):
        return False
