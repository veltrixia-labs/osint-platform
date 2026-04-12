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
        
        # 1. Get known stakeholders and calculate Quantum Indices
        from processor.impact_calculator import ImpactCalculator
        known_stakes = await self.get_all_stakeholders()
        stakeholder_context = []
        
        for s in known_stakes[:15]: # Limit context to top 15 for token efficiency
            indices = await ImpactCalculator.evaluate_sociographic_indices(self.db, s.id)
            stakeholder_context.append({
                "id": str(s.id),
                "name": s.name,
                "domain": s.domain,
                "quantum_indices": indices
            })

        system_prompt = (
            "You are an OSINT Intelligence Architect. Your task is to analyze cascading ripple effects "
            "as a DIVERGENT BRANCHING CAUSAL TREE (Order 1 -> Order 2 -> Order 3).\n\n"
            "CONTEXTUAL DATA: You are provided with SOCIOGRAPHIC INDICATORS for stakeholders:\n"
            "- Resilience (Omega): Ability to substitute/recover.\n"
            "- Contagion (Delta-C): Probability of impact transfer.\n"
            "- Fragility (FRG): Structural vulnerability.\n\n"
            "COGNITIVE DIRECTIVES:\n"
            "1. METRIC-DRIVEN JUSTIFICATION: Use the provided Quantum Indices to justify the magnitude of impact.\n"
            "2. ACTIONABLE ADVICE: For every finding, provide a 'containment_action' (Actionable recommendation).\n"
            "3. TIMELINE: Estimate 'time_to_impact' (e.g., 'Immediate', '3-5 Days', '2 Weeks').\n"
            "4. FAN-OUT: Identify 3 distinct Level 1 entities, and branch secondary effects.\n\n"
            "Strictly return nested branching JSON:\n"
            "{\n"
            "  'findings': [\n"
            "    {\n"
            "      'entity_name': '...', \n"
            "      'impact_alpha': -5.0,\n"
            "      'impact_summary': '...', \n"
            "      'reasoning': '...', \n"
            "      'containment_action': '...', \n"
            "      'time_to_impact': '...', \n"
            "      'cascading_impacts': [...] \n"
            "    }\n"
            "  ]\n"
            "}"
        )

        user_prompt = (
            f"SIGNAL TITLE: {title}\n"
            f"SIGNAL SUMMARY: {summary}\n\n"
            f"SOCIOGRAPHIC BASELINE (Context):\n{json.dumps(stakeholder_context, indent=2)}"
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
                
                # [v10.18] Quantum Metric Enrichment
                # If we have a stakeholder, fetch their real-time sociographic indices
                try:
                    # 1. Coordinate & Metadata Enrichment
                    if s_id and s_id != "null":
                        s_stmt = select(Stakeholder).where(Stakeholder.id == uuid.UUID(s_id))
                        stakeholder = (await self.db.execute(s_stmt)).scalar_one_or_none()
                    elif not s_id and finding.get("entity_name"):
                        # Fallback: Fuzzy Name Match if LLM didn't provide ID
                        fuzzy_stmt = select(Stakeholder).where(Stakeholder.name.ilike(f"%{finding['entity_name']}%"))
                        stakeholder = (await self.db.execute(fuzzy_stmt)).first()
                        if stakeholder: stakeholder = stakeholder[0]

                    if stakeholder:
                        finding["stakeholder_id"] = str(stakeholder.id)
                        finding["location_lat"] = stakeholder.location_lat
                        finding["location_lng"] = stakeholder.location_lng
                        
                        # Calculate Indices
                        indices = await ImpactCalculator.evaluate_sociographic_indices(self.db, stakeholder.id)
                        finding["quantum_metrics"] = indices

                        # Create Prediction record
                        pred = Prediction(
                            prediction_id=f"PRED-{uuid.uuid4().hex[:8].upper()}",
                            trigger_event=f"{title}: {summary[:200]}...",
                            target_id=stakeholder.id,
                            predicted_alpha=finding.get("impact_alpha", 0.0),
                            confidence_score=finding.get("confidence", 0.7),
                            is_evaluated=False
                        )
                        self.db.add(pred)
                    else:
                        # Fallback metrics for unknown entities
                        finding["quantum_metrics"] = {
                            "resilience": 45.0, 
                            "contagion": 0.4, 
                            "fragility": 0.5,
                            "metrics_source": "probabilistic_estimation"
                        }
                except Exception as ex:
                    logger.warning(f"Failed to enrich stakeholder {s_id}: {ex}")

                # Recurse
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
