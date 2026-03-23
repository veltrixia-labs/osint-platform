
import asyncio
import os
import sys
from sqlalchemy import select, update
import uuid

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from db.database import AsyncSessionLocal
from db.models import Report, AnalystProfile
from db.enums import PlanTier
from api.gating import is_tier_sufficient

async def verify_gating():
    print("--- STARTING API GATING VERIFICATION ---")
    
    async with AsyncSessionLocal() as db:
        # 1. Ensure we have a report that requires "pro"
        # We'll temporarily update one or create one
        print("Ensuring a 'pro' report exists...")
        stmt_rep = select(Report).limit(1)
        r = (await db.execute(stmt_rep)).scalar_one_or_none()
        if not r:
            print("No reports found to test gating.")
            return
            
        original_plan = r.plan_required
        r.plan_required = "pro"
        await db.commit()
        
        # 2. Test tier sufficiency logic
        print(f"Testing tier sufficiency for report requiring 'pro':")
        
        print(f"  User=Free, Req=Pro -> Sufficient? {is_tier_sufficient('free', 'pro')}")
        if not is_tier_sufficient('free', 'pro'):
            print("  [OK] Gating logic would block Free user.")
        else:
            print("  [FAIL] Gating logic failed to block Free user.")

        print(f"  User=Pro, Req=Pro -> Sufficient? {is_tier_sufficient('pro', 'pro')}")
        if is_tier_sufficient('pro', 'pro'):
            print("  [OK] Gating logic allows Pro user.")
        else:
            print("  [FAIL] Gating logic blocked Pro user.")

        print(f"  User=Experts, Req=Pro -> Sufficient? {is_tier_sufficient('experts', 'pro')}")
        if is_tier_sufficient('experts', 'pro'):
            print("  [OK] Gating logic allows Expert user.")
        else:
            print("  [FAIL] Gating logic blocked Expert user.")

        # 3. Clean up
        r.plan_required = original_plan
        await db.commit()

    print("\n--- GATING VERIFICATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(verify_gating())
