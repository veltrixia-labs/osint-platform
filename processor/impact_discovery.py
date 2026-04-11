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
            "You are an Advanced Geopolitical & Market Intelligence Analyst. Your task is to analyze cascading ripple effects "
            "through three specific lenses:\n"
            "1. GEOPOLITICAL POWER: How does this signal shift regional influence, alliances, or security dynamics?\n"
            "2. HISTORICAL PRECEDENCE: Does this pattern match known historical conflicts, market crashes, or social upheavals?\n"
            "3. SOCIAL-LEGAL IMPACT: Potential for civil unrest, major regulatory shifts, or systemic instability.\n\n"
            "TASK:\n"
            "Identify 3 secondary stakeholders (Companies, Organizations, or Market Segments) affected by this signal.\n"
            "Predict the 'Impact Alpha' (expected movement relative to S&P 500) over a 7-day horizon.\n\n"
            "Strictly return JSON:\n"
            "{\n"
            "  'findings': [\n"
            "    {\n"
            "      'stakeholder_id': 'UUID or null',\n"
            "      'entity_name': 'Entity Name',\n"
            "      'impact_direction': 'positive/negative',\n"
            "      'impact_alpha': -5.0,\n"
            "      'confidence': 0.85,\n"
            "      'source': 'ai_reasoning',\n"
            "      'reasoning': 'Explain via the Geopolitical/Historical/Social context requested.'\n"
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

            processed_findings = []

            for f in findings:
                # 2. Log Prediction to DB if we have a valid stakeholder_id
                s_id = f.get("stakeholder_id")
                stakeholder = None
                if s_id and s_id != "null":
                    # Get stakeholder for metadata
                    s_stmt = select(Stakeholder).where(Stakeholder.id == uuid.UUID(s_id))
                    stakeholder = (await self.db.execute(s_stmt)).scalar_one_or_none()
                    
                    # Create Prediction record
                    pred = Prediction(
                        prediction_id=f"PRED-{uuid.uuid4().hex[:8].upper()}",
                        trigger_event=f"{title}: {summary[:200]}...",
                        target_id=uuid.UUID(s_id),
                        predicted_alpha=f.get("impact_alpha", 0.0),
                        confidence_score=f.get("confidence", 0.0),
                        is_evaluated=False
                    )
                    self.db.add(pred)
                
                # Enrich finding with spatial metadata for UI
                if stakeholder:
                    f["location_lat"] = stakeholder.location_lat
                    f["location_lng"] = stakeholder.location_lng
                
                processed_findings.append(f)

            await self.db.commit()
            
            # 3. Store in Cache
            _discovery_cache[event_hash] = (datetime.now(timezone.utc), processed_findings)
            
            return processed_findings

        except Exception as e:
            logger.error(f"Error in ImpactDiscoveryEngine: {e}")
            await self.db.rollback()
            return []
