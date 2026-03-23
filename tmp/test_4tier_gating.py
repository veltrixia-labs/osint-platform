import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from db.enums import PlanTier, ReportType, TIER_ORDER, is_tier_sufficient
from api.gating import (
    can_access_report_type, get_plan_limits, 
    TIER_FREE, TIER_PRO, TIER_EXPERTS, TIER_ENTERPRISE
)

async def test_gating():
    print("--- Testing Tier Order ---")
    print(f"TIER_ORDER: {TIER_ORDER}")
    assert PlanTier.FREE in TIER_ORDER
    assert PlanTier.PRO in TIER_ORDER
    assert PlanTier.EXPERTS in TIER_ORDER
    assert PlanTier.ENTERPRISE in TIER_ORDER
    assert TIER_ORDER.index(PlanTier.EXPERTS) < TIER_ORDER.index(PlanTier.ENTERPRISE)
    print("Tier Order OK")

    print("\n--- Testing is_tier_sufficient ---")
    assert is_tier_sufficient(TIER_PRO, TIER_FREE) is True
    assert is_tier_sufficient(TIER_PRO, TIER_PRO) is True
    assert is_tier_sufficient(TIER_PRO, TIER_EXPERTS) is False
    assert is_tier_sufficient(TIER_EXPERTS, TIER_PRO) is True
    assert is_tier_sufficient(TIER_EXPERTS, TIER_EXPERTS) is True
    assert is_tier_sufficient(TIER_EXPERTS, TIER_ENTERPRISE) is False
    assert is_tier_sufficient(TIER_ENTERPRISE, TIER_EXPERTS) is True
    print("is_tier_sufficient OK")

    print("\n--- Testing can_access_report_type ---")
    # Pro Access
    assert can_access_report_type(TIER_PRO, ReportType.DAILY) is True
    assert can_access_report_type(TIER_PRO, ReportType.WEEKLY) is True
    assert can_access_report_type(TIER_PRO, ReportType.MONTHLY) is False
    print("Pro Report Access OK (No Monthly)")

    # Experts Access
    assert can_access_report_type(TIER_EXPERTS, ReportType.DAILY) is True
    assert can_access_report_type(TIER_EXPERTS, ReportType.WEEKLY) is True
    assert can_access_report_type(TIER_EXPERTS, ReportType.MONTHLY) is True
    print("Experts Report Access OK (Daily+Weekly+Monthly)")

    # Enterprise Access
    assert can_access_report_type(TIER_ENTERPRISE, ReportType.MONTHLY) is True
    print("Enterprise Report Access OK")

    print("\n--- Testing Plan Limits ---")
    pro_limits = get_plan_limits(TIER_PRO)
    experts_limits = get_plan_limits(TIER_EXPERTS)
    ent_limits = get_plan_limits(TIER_ENTERPRISE)

    assert pro_limits["alerts_per_day"] == 100
    assert experts_limits["alerts_per_day"] == "unlimited"
    assert ent_limits["custom_topics"] is True
    assert experts_limits.get("custom_topics") is None
    print("Plan Limits OK (Custom Topics restricted to Enterprise)")

    print("\nALL BACKEND GATING TESTS PASSED!")

if __name__ == "__main__":
    asyncio.run(test_gating())
