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

# ★ Retired 2026-10-06 (operator decision: Pro Insight supersedes them). Weekly and monthly
#   reports were generated but shown on no reachable surface: the only UI path was the dead
#   'reports' tab, and Pro Insight serves pro_structural only. Generation is refused for these
#   types (jobs/report_generator.py) and the retention job deletes any existing rows regardless
#   of age (jobs/cleanup_job.py).
RETIRED_REPORT_TYPES = ("weekly", "monthly")

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
