import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath("."))

try:
    from db.enums import is_tier_sufficient, PlanTier
    
    test_cases = [
        ("free", "free", True),
        ("free", "pro", False),
        ("pro", "free", True),
        ("pro", "pro", True),
        ("pro", "experts", False),
        ("experts", "pro", True),
        ("enterprise", "experts", True),
        (PlanTier.PRO, "free", True),
        ("pro", PlanTier.EXPERTS, False),
    ]
    
    passed = True
    for u, r, expected in test_cases:
        res = is_tier_sufficient(u, r)
        if res != expected:
            print(f"FAILED: is_tier_sufficient({u}, {r}) -> {res} (Expected {expected})")
            passed = False
        else:
            print(f"PASSED: is_tier_sufficient({u}, {r}) -> {res}")
            
    if passed:
        print("\nAll tier sufficiency tests PASSED.")
    else:
        print("\nSome tests FAILED.")
        sys.exit(1)
except Exception as e:
    print(f"ERROR during verification: {e}")
    sys.exit(1)
