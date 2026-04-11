import logging
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.models import Stakeholder, Dependency, Prediction
from llm.client import generate_analysis

logger = logging.getLogger(__name__)

# Global Discovery Cache to preserve LLM quota
_discovery_cache = {}
CACHE_TTL_HOURS = 6

class ImpactDiscoveryEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_stakeholders(self) -> List[Stakeholder]:
        stmt = select(Stakeholder)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def run_discovery(self, trigger_item_id: uuid.UUID, title: str, summary: str) -> List[Dict[str, Any]]:
        """
        Extract stakeholders and predict impacts from a news/alert signal.
        Includes a deduplication cache to preserve LLM quota.
        """
        import hashlib
        # 0. Deduplication Check
        event_hash = hashlib.md5(f"{title}:{summary[:100]}".encode()).hexdigest()
        cached_result = _discovery_cache.get(event_hash)
        if cached_result:
            # Check TTL
            ts, data = cached_result
            if datetime.now(timezone.utc) - ts < timedelta(hours=CACHE_TTL_HOURS):
                logger.info(f"Using cached impact discovery for event hash: {event_hash}")
                return data

        logger.info(f"Running LLM Impact Discovery for: {title}")
        
        # 1. Get known stakeholders for context (to improve matching)
        known_stakes = await self.get_all_stakeholders()
        stakeholder_context = [
            {"id": str(s.id), "name": s.name, "ticker": s.ticker, "domain": s.domain}
            for s in known_stakes
        ]

        system_prompt = (
            "You are an OSINT Intelligence Architect. Your task is to analyze cascading ripple effects "
            "as a DIVERGENT BRANCHING CAUSAL TREE (Order 1 -> Order 2 -> Order 3).\n\n"
            "COGNITIVE DIRECTIVES:\n"
            "1. FAN-OUT: From the source (Alert), identify at least 3 distinct DIRECT (Level 1) stake-holders "
            "(Companies, Shipping, Market Sectors, or Facilities).\n"
            "2. SECONDARY BRANCHING: For each Level 1 entity, identify 1-2 SPECIFIC secondary (Level 2) effects.\n"
            "3. IMPACT SUMMARY: Provide a extremely short 'impact_summary' (3-5 words) for each node (e.g., 'Production Delays', 'Supply Shortage').\n\n"
            "Strictly return nested branching JSON:\n"
            "{\n"
            "  'findings': [\n"
            "    {\n"
            "      'entity_name': '...', \n"
            "      'impact_alpha': -5.0,\n"
            "      'impact_summary': 'Direct Market Volatility',\n"
            "      'reasoning': '...', \n"
            "      'cascading_impacts': [\n"
            "        {\n"
            "          'entity_name': '...', \n"
            "          'impact_summary': 'Component Shortage',\n"
            "          'cascading_impacts': [...] \n"
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}"
        )

        user_prompt = (
            f"SIGNAL TITLE: {title}\n"
            f"SIGNAL SUMMARY: {summary}\n\n"
            f"KNOWN STAKEHOLDERS (Context):\n{json.dumps(stakeholder_context, indent=2)}"
        )

        try:
            analysis = await generate_analysis(system_prompt, user_prompt, is_batch=False)
            findings = analysis.get("findings", [])
            
            # [v10.9] Statistical Fallback: If AI is empty or degraded, use numerical model
            if not findings:
                logger.info(f"AI returned empty findings for {title}. Triggering Statistical Fallback.")
                from processor.impact_calculator import ImpactCalculator
                findings = ImpactCalculator.calculate_impacts(
                    topic=summary.split(' ')[0], # Rough topic extraction or pass from caller
                    lat=None, lng=None, 
                    intensity=5.0 # Default fallback intensity
                )

            async def enrich_finding(finding: Dict[str, Any]):
                # Enforce source if missing
                if "source" not in finding:
                    finding["source"] = "ai_reasoning"
                
                s_id = finding.get("stakeholder_id")
                stakeholder = None
                if s_id and s_id != "null":
                    try:
                        s_stmt = select(Stakeholder).where(Stakeholder.id == uuid.UUID(s_id))
                        stakeholder = (await self.db.execute(s_stmt)).scalar_one_or_none()
                        
                        if stakeholder:
                            finding["location_lat"] = stakeholder.location_lat
                            finding["location_lng"] = stakeholder.location_lng
                            
                        # Create Prediction record for tracking
                        pred = Prediction(
                            prediction_id=f"PRED-{uuid.uuid4().hex[:8].upper()}",
                            trigger_event=f"{title}: {summary[:200]}...",
                            target_id=uuid.UUID(s_id),
                            predicted_alpha=finding.get("impact_alpha", 0.0),
                            confidence_score=finding.get("confidence", 0.0),
                            is_evaluated=False
                        )
                        self.db.add(pred)
                    except Exception as ex:
                        logger.warning(f"Failed to enrich stakeholder {s_id}: {ex}")

                # Recurse into children
                children = finding.get("cascading_impacts", [])
                for child in children:
                    await enrich_finding(child)

            processed_findings = []
            for f in findings:
                await enrich_finding(f)
                processed_findings.append(f)

            await self.db.commit()
            
            # 3. Store in Cache
            _discovery_cache[event_hash] = (datetime.now(timezone.utc), processed_findings)
            
            return processed_findings

        except Exception as e:
            logger.error(f"Error in ImpactDiscoveryEngine: {e}")
            await self.db.rollback()
            return []
