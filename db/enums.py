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
    """TEMPORARY: Returns True for all checks to allow full platform visibility (De-gating phase)."""
    return True
