import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath("."))

try:
    from api.gating import is_topic_allowed, can_access_report_type, _gate_cascading_impacts
    from db.enums import PlanTier, ReportType
    
    print("--- Testing is_topic_allowed ---")
    topics = [
        ("free", "global", True),
        ("free", "defense_technology", False),
        ("pro", "defense_technology", True),
        ("experts", "energy_resource_risk", True),
        (None, "global", True),
        (None, "energy_resource_risk", False)
    ]
    for tier, topic, expected in topics:
        res = is_topic_allowed(tier, topic)
        print(f"[{tier} | {topic}] Expected: {expected}, Got: {res}")
        assert res == expected

    print("\n--- Testing can_access_report_type ---")
    reports = [
        ("free", ReportType.DAILY.value, True),
        ("free", ReportType.WEEKLY.value, False),
        ("pro", ReportType.WEEKLY.value, True),
        ("pro", ReportType.MONTHLY.value, False),
        ("experts", ReportType.MONTHLY.value, True)
    ]
    for tier, rtype, expected in reports:
        res = can_access_report_type(tier, rtype)
        print(f"[{tier} | {rtype}] Expected: {expected}, Got: {res}")
        assert res == expected

    print("\n--- Testing _gate_cascading_impacts ---")
    impacts = [
        {"id": 1, "level": 1},
        {"id": 2, "level": 2},
        {"id": 3, "level": 3},
        {"id": 4, "level": 4}
    ]
    # Free
    res_free = _gate_cascading_impacts("free", impacts)
    print(f"[free] Count: {len(res_free)} (Expected 0)")
    assert len(res_free) == 0
    
    # Pro
    res_pro = _gate_cascading_impacts("pro", impacts)
    print(f"[pro] Count: {len(res_pro)} (Expected 2, levels 1 and 2)")
    assert len(res_pro) == 2
    assert all(i["level"] <= 2 for i in res_pro)
    
    # Expert
    res_exp = _gate_cascading_impacts("experts", impacts)
    print(f"[experts] Count: {len(res_exp)} (Expected {len(impacts)})")
    assert len(res_exp) == len(impacts)

    print("\nAll gating logic tests PASSED.")
except Exception as e:
    print(f"\nERROR during verification: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
LineContent = """
"""
