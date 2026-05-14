"""
Pro Structural Brief Automation Manager.

Orchestrates the automated generation of Pro-tier structural briefs by 
evaluating candidates against trigger policies and operational caps.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import Report, AlertLog
from jobs.pro_brief_trigger_policy import select_candidate_alerts_for_pro_briefs
from jobs.pro_report_generator import run_pro_structural_report_generation

logger = logging.getLogger(__name__)

class ProAutomationManager:
    """
    Manager for Pro Structural Brief automation cycles.
    """
    
    # Operational Caps
    MAX_DAILY_REPORTS = 5
    MAX_REPORTS_PER_DOMAIN_PER_DAY = 1

    def __init__(self, db: AsyncSession):
        self.db = db
        self.enabled_domains = self._get_enabled_domains()

    def _get_enabled_domains(self) -> List[str]:
        """Reads enabled domains from environment variable."""
        val = os.getenv("PRO_AUTOMATION_ENABLED_DOMAINS", "")
        if not val:
            return []
        if val.lower() == "all":
            return ["all"]
        return [d.strip() for d in val.split(",") if d.strip()]

    async def count_reports_generated_today(self) -> int:
        """
        Counts Pro Structural reports generated in the last 24 hours.
        """
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)
        
        stmt = select(func.count(Report.id)).where(
            Report.plan_required == "pro",
            Report.is_premium == True,
            Report.created_at >= yesterday,
            or_(
                Report.report_type == "pro_structural",
                Report.title.ilike("Structural Impact Brief%")
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def count_reports_by_domain_today(self, domain_id: str) -> int:
        """
        Counts Pro Structural reports for a specific domain generated in the last 24 hours.
        """
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)
        
        stmt = select(func.count(Report.id)).where(
            Report.plan_required == "pro",
            Report.topic_code == domain_id,
            Report.created_at >= yesterday,
            or_(
                Report.report_type == "pro_structural",
                Report.title.ilike("Structural Impact Brief%")
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def run_once(
        self,
        limit: int = 5,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Executes a single automation cycle: selects candidates, checks caps, and generates reports.
        """
        results = {
            "dry_run": dry_run,
            "candidates_found": 0,
            "generated_count": 0,
            "skipped_count": 0,
            "errors_count": 0,
            "generated_reports": [],
            "skipped": [],
            "candidates": []
        }
        
        # 1. Fetch candidates based on trigger policy (Scan up to 50 recent candidates)
        candidates = await select_candidate_alerts_for_pro_briefs(self.db, limit=50)
        results["candidates_found"] = len(candidates)
        results["candidates"] = candidates
        
        if not candidates:
            return results

        # 2. Check Daily Cap
        current_daily_count = await self.count_reports_generated_today()
        if current_daily_count >= self.MAX_DAILY_REPORTS:
            results["skipped"].append({
                "reason": f"System-wide daily cap reached ({current_daily_count}/{self.MAX_DAILY_REPORTS})"
            })
            results["skipped_count"] = len(candidates)
            return results

        # 3. Process Candidates
        remaining_daily_quota = self.MAX_DAILY_REPORTS - current_daily_count
        
        for candidate in candidates:
            if remaining_daily_quota <= 0:
                results["skipped"].append({
                    "alert_id": candidate["alert_id"],
                    "reason": "Daily quota exhausted during processing"
                })
                results["skipped_count"] += 1
                continue

            alert_id = candidate["alert_id"]
            topic = candidate["topic"]
            domain_id = candidate["diagnostics"]["metrics"].get("domain_id")
            
            if not domain_id:
                results["skipped"].append({
                    "alert_id": alert_id,
                    "reason": "Invalid or missing domain_id"
                })
                results["skipped_count"] += 1
                continue

            # 4. Check if Domain is Enabled for Automation
            if "all" not in self.enabled_domains and domain_id not in self.enabled_domains:
                reason = f"Domain not enabled for automation: '{domain_id}' (Enabled: {self.enabled_domains})"
                results["skipped"].append({
                    "alert_id": alert_id,
                    "domain_id": domain_id,
                    "reason": reason
                })
                results["skipped_count"] += 1
                logger.info(f"  [SKIP] Alert {alert_id} ({domain_id}): {reason}")
                continue

            # Data availability check from diagnostics
            has_structural = candidate["diagnostics"].get("has_structural", False)
            has_market = candidate["diagnostics"].get("has_market", False)
            
            if not has_structural or not has_market:
                reason = f"Data missing: Structural={has_structural}, Market={has_market}"
                results["skipped"].append({
                    "alert_id": alert_id,
                    "domain_id": domain_id,
                    "reason": reason
                })
                results["skipped_count"] += 1
                logger.info(f"  [SKIP] Alert {alert_id} ({domain_id}): {reason}")
                continue

            # 5. Check Domain Cap
            domain_count = await self.count_reports_by_domain_today(domain_id)
            if domain_count >= self.MAX_REPORTS_PER_DOMAIN_PER_DAY:
                reason = f"Domain cap reached for '{domain_id}' ({domain_count}/{self.MAX_REPORTS_PER_DOMAIN_PER_DAY})"
                results["skipped"].append({
                    "alert_id": alert_id,
                    "domain_id": domain_id,
                    "reason": reason
                })
                results["skipped_count"] += 1
                logger.info(f"  [SKIP] Alert {alert_id} ({domain_id}): {reason}")
                continue

            # 6. Generate Report
            if dry_run:
                results["generated_reports"].append({
                    "alert_id": alert_id,
                    "domain_id": domain_id,
                    "status": "planned",
                    "title": f"Planned: Structural Impact Brief - {domain_id}"
                })
                results["generated_count"] += 1
                remaining_daily_quota -= 1
            else:
                try:
                    report = await run_pro_structural_report_generation(
                        alert_id=alert_id,
                        domain_id=domain_id,
                        report_type="weekly"
                    )
                    results["generated_reports"].append({
                        "alert_id": alert_id,
                        "report_id": str(report.id),
                        "title": report.title,
                        "status": "generated"
                    })
                    results["generated_count"] += 1
                    remaining_daily_quota -= 1
                    logger.info(f"Automated Pro report generated: {report.id} for alert {alert_id}")
                except Exception as e:
                    logger.error(f"Failed to generate automated Pro report for alert {alert_id}: {e}")
                    results["errors_count"] += 1
                    results["skipped"].append({
                        "alert_id": alert_id,
                        "reason": f"Generation error: {str(e)}"
                    })

        return results

async def run_scheduled_pro_automation() -> Dict[str, Any]:
    """
    Wrapper for scheduler integration. Reads ENV and runs the automation cycle.
    """
    enabled = os.getenv("ENABLE_PRO_AUTOMATION", "false").lower() == "true"
    dry_run = os.getenv("PRO_AUTOMATION_DRY_RUN", "true").lower() == "true"
    limit = int(os.getenv("PRO_AUTOMATION_LIMIT", "5"))
    
    if not enabled:
        logger.info("Pro Structural Brief Automation is DISABLED (ENABLE_PRO_AUTOMATION=false).")
        return {"status": "disabled", "skipped": True}

    logger.info(f"Starting Pro Structural Brief Automation (dry_run={dry_run}, limit={limit})")
    
    try:
        async with AsyncSessionLocal() as db:
            manager = ProAutomationManager(db)
            enabled_domains = manager.enabled_domains
            logger.info(f"Enabled Pro Domains: {enabled_domains}")
            
            results = await manager.run_once(limit=limit, dry_run=dry_run)
            
            logger.info(
                f"Pro Automation Cycle Finished: Found={results['candidates_found']}, "
                f"Planned={results['generated_count']}, Skipped={results['skipped_count']}, "
                f"Errors={results['errors_count']}"
            )
            
            if results["skipped"]:
                logger.info("Detailed Skip Reasons:")
                for s in results["skipped"][:10]: # Log first 10
                    logger.info(f"  - Alert {s.get('alert_id', 'N/A')} ({s.get('domain_id', 'N/A')}): {s['reason']}")
            
            if results["generated_reports"]:
                logger.info("Candidates Slated for Generation:")
                for r in results["generated_reports"]:
                    logger.info(f"  - {r['title']} (Alert: {r['alert_id']})")
                    
            return results
    except Exception as e:
        logger.error(f"FATAL: Pro Automation Job failed with exception: {e}")
        return {"status": "error", "error": str(e)}
