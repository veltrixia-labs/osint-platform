import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from db.models import AlertLog, Report
from jobs.pro_brief_trigger_policy import should_generate_pro_brief

async def test_policy():
    print("=" * 80)
    print("TESTING PRO BRIEF TRIGGER POLICY LOGIC")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        # 1. Test Case: Perfect Structural Candidate (Severity Watch, but high quality)
        # We don't save to DB, just use objects
        mock_alert = AlertLog(
            id=uuid.uuid4(),
            topic="ai_semiconductor_intelligence",
            target_label="NVIDIA Next-Gen GPU Leak",
            severity="watch",
            intelligence_score=0.7,
            is_high_fidelity=True,
            supporting_events_count=5,
            triggered_at=datetime.now(timezone.utc),
            metadata_json={"source_count": 5, "related_news_count": 10}
        )
        
        print("\n[TEST 1] High-Quality Watch Alert (Promoted Candidate)")
        should_gen, reasons, diag = await should_generate_pro_brief(db, mock_alert)
        print(f"  Should Generate: {should_gen}")
        print(f"  Reasons: {reasons}")
        print(f"  Diagnostics: {diag}")
        
        # 2. Test Case: Structural Duplicate
        print("\n[TEST 2] Structural Duplicate (Absolute Blocker)")
        # Insert a temporary report for the test
        temp_report = Report(
            report_type="pro_structural",
            topic_code="ai_semiconductor_intelligence",
            plan_required="pro",
            title="Structural Impact Brief - AI Semiconductor",
            created_at=datetime.now(timezone.utc)
        )
        db.add(temp_report)
        await db.flush()
        
        should_gen, reasons, diag = await should_generate_pro_brief(db, mock_alert)
        print(f"  Should Generate: {should_gen}")
        print(f"  Reasons: {reasons}")
        print(f"  Duplicate Info: Structural={diag.get('duplicate_structural_brief')}, General={diag.get('duplicate_general_report')}")

        # 3. Test Case: General Duplicate (Should not block if we change policy, but currently does)
        print("\n[TEST 3] General Duplicate Only")
        # Remove structural, add general
        await db.delete(temp_report)
        general_report = Report(
            report_type="weekly", # General type
            topic_code="ai_semiconductor_intelligence",
            plan_required="pro",
            title="Weekly Market Intelligence",
            created_at=datetime.now(timezone.utc)
        )
        db.add(general_report)
        await db.flush()
        
        should_gen, reasons, diag = await should_generate_pro_brief(db, mock_alert)
        print(f"  Should Generate: {should_gen}")
        print(f"  Reasons: {reasons}")
        print(f"  Duplicate Info: Structural={diag.get('duplicate_structural_brief')}, General={diag.get('duplicate_general_report')}")

        # 4. Test Case: Global Market Relaxed Candidate (PASS)
        print("\n[TEST 4] Global Market Relaxed Candidate (Experimental Rescue)")
        gm_alert = AlertLog(
            id=uuid.uuid4(),
            topic="global_market_intelligence",
            target_label="Central Bank Liquidity Shift",
            severity="watch",
            intelligence_score=0.4, # Above 0.3
            fidelity_score=0.65,    # Above 0.6 but below 0.8
            supporting_events_count=4, # Evidence 4+
            triggered_at=datetime.now(timezone.utc),
            metadata_json={"source_count": 4}
        )
        should_gen, reasons, diag = await should_generate_pro_brief(db, gm_alert)
        print(f"  Should Generate: {should_gen}")
        print(f"  Reasons: {reasons}")
        print(f"  Diagnostics: passed_gm_relaxed={diag.get('passed_global_market_relaxed_gate')}, reason={diag.get('relaxed_gate_reason')}")

        # 5. Test Case: Supply Chain - No Relaxation (FAIL)
        print("\n[TEST 5] Supply Chain - No Relaxation (Should Fail if Fidelity < 0.8)")
        sc_alert = AlertLog(
            id=uuid.uuid4(),
            topic="supply_chain_intelligence",
            target_label="Port Congestion Spike",
            severity="watch",
            intelligence_score=0.4,
            fidelity_score=0.65, # Same as GM, but for SC this is too low
            supporting_events_count=4,
            triggered_at=datetime.now(timezone.utc),
            metadata_json={"source_count": 4}
        )
        should_gen, reasons, diag = await should_generate_pro_brief(db, sc_alert)
        print(f"  Should Generate: {should_gen}")
        print(f"  Reasons: {reasons}")
        print(f"  Fidelity Gate: {diag.get('passed_fidelity_gate')}")

        # 6. Test Case: Global Market Relaxed but Duplicate (FAIL)
        print("\n[TEST 6] Global Market Relaxed but Duplicate (Absolute Blocker)")
        gm_dup_report = Report(
            report_type="pro_structural",
            topic_code="global_market_intelligence",
            plan_required="pro",
            title="Structural Impact Brief - Global Market",
            created_at=datetime.now(timezone.utc)
        )
        db.add(gm_dup_report)
        await db.flush()
        
        should_gen, reasons, diag = await should_generate_pro_brief(db, gm_alert)
        print(f"  Should Generate: {should_gen}")
        print(f"  Reasons: {reasons}")
        print(f"  Passed GM Relaxed Gate: {diag.get('passed_global_market_relaxed_gate')}")

        await db.rollback() # Don't commit tests

if __name__ == "__main__":
    asyncio.run(test_policy())
