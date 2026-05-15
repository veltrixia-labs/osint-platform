import asyncio
import sys
import os
import logging
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import AsyncSessionLocal
from jobs.pro_automation_manager import ProAutomationManager

async def test_all_domains_enabled():
    async with AsyncSessionLocal() as db:
        print("=" * 70)
        print("TESTING 'ALL' DOMAINS ENABLED LOGIC")
        print("=" * 70)

        # Mock environment variables
        os.environ["PRO_AUTOMATION_ENABLED_DOMAINS"] = "all"
        
        manager = ProAutomationManager(db)
        print(f"Enabled Domains: {manager.enabled_domains}")

        # Mock candidates for various domains
        mock_candidates = [
            {
                "alert_id": "alert-defense",
                "topic": "defense_technology",
                "diagnostics": {"metrics": {"domain_id": "defense_technology"}}
            },
            {
                "alert_id": "alert-global",
                "topic": "global_market_intelligence",
                "diagnostics": {"metrics": {"domain_id": "global_market_intelligence"}}
            }
        ]

        async def mock_fetch(*args, **kwargs):
            return mock_candidates

        with patch("jobs.pro_automation_manager.select_candidate_alerts_for_pro_briefs", side_effect=mock_fetch):
            with patch.object(manager, "count_reports_generated_today", return_value=0):
                with patch.object(manager, "count_reports_by_domain_today", return_value=0):
                    results = await manager.run_once(limit=10, dry_run=True)

        print(f"\nCandidates Evaluated: {len(mock_candidates)}")
        print(f"Planned to Generate: {results['generated_count']}")
        print(f"Skipped: {results['skipped_count']}")

        generated_domains = [r["domain_id"] for r in results["generated_reports"]]
        print(f"Generated Domains: {generated_domains}")
        
        assert "defense_technology" in generated_domains
        assert "global_market_intelligence" in generated_domains
        
        print("\n[SUCCESS] 'all' logic is working correctly.")

if __name__ == "__main__":
    asyncio.run(test_all_domains_enabled())
