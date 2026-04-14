import logging
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified
from db.models import Stakeholder, Dependency, Prediction
from llm.client import generate_analysis

logger = logging.getLogger(__name__)

# Global Discovery Cache to preserve LLM quota
_discovery_cache = {}
CACHE_TTL_HOURS = 6

class ImpactDiscoveryEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_top_stakeholders(self, limit: int = 15, domain: Optional[str] = None) -> List[Stakeholder]:
        stmt = select(Stakeholder)
        if domain and domain != "global":
            stmt = stmt.where(Stakeholder.domain == domain)
        stmt = stmt.order_by(Stakeholder.strategic_score.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def _auto_provision_stakeholder(self, finding: Dict[str, Any]) -> Optional[Stakeholder]:
        """
        [v10.19] Auto-Registration Engine.
        If an entity identified by LLM is not in DB, create it with AI-inferred coordinates and sector.
        """
        entity_name = finding.get("entity_name", "Unknown Entity")
        entity_lat = finding.get("entity_lat")
        entity_lng = finding.get("entity_lng")
        entity_sector = finding.get("entity_sector", "global")

        if not entity_lat or not entity_lng:
            logger.warning(f"[Antigravity] Auto-Provision skipped for '{entity_name}': No coordinates provided by LLM.")
            return None

        # Map LLM sector string to DB domain code
        domain_map = {
            "semiconductor": "ai_semi", "tech": "ai_semi", "ai": "ai_semi",
            "energy": "energy", "oil": "energy", "gas": "energy",
            "shipping": "supply_chain", "supply": "supply_chain", "logistics": "supply_chain",
            "market": "market", "finance": "market", "banking": "market",
            "defense": "defense", "military": "defense",
            "crypto": "crypto", "blockchain": "crypto",
        }
        domain = "global"
        for key, val in domain_map.items():
            if key in entity_sector.lower():
                domain = val
                break

        new_stakeholder = Stakeholder(
            id=uuid.uuid4(),
            name=entity_name,
            sector=entity_sector,
            country=finding.get("entity_country", "Unknown"),
            domain=domain,
            description=f"Auto-provisioned by AI during impact discovery on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.",
            location_lat=float(entity_lat),
            location_lng=float(entity_lng),
            is_auto_provisioned=True,   # [v10.21] Tactical node — subject to lifecycle pruning
            strategic_score=0.0,
            hit_count=1,
            last_hit_at=datetime.now(timezone.utc),
        )
        self.db.add(new_stakeholder)
        logger.info(f"[Antigravity] AUTO-PROVISIONED Stakeholder: '{entity_name}' at ({entity_lat}, {entity_lng}) in domain '{domain}'")
        return new_stakeholder

    async def run_discovery(self, trigger_item_id: uuid.UUID, title: str, summary: str, alert_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
        """
        Extract stakeholders and predict impacts from a news/alert signal.
        Includes a deduplication cache to preserve LLM quota.
        """
        import hashlib
        # 0. Deduplication Check
        event_hash = hashlib.md5(f"{title}:{summary[:100]}".encode()).hexdigest()
        cached_result = _discovery_cache.get(event_hash)
        if cached_result:
            ts, data = cached_result
            if datetime.now(timezone.utc) - ts < timedelta(hours=CACHE_TTL_HOURS):
                logger.info(f"Using cached impact discovery for event hash: {event_hash}")
                return data

        logger.info(f"Running LLM Impact Discovery for: {title}")
        
        # 1. Get known stakeholders and calculate Quantum Indices (Topic-Aware)
        from processor.impact_calculator import ImpactCalculator
        
        # [v10.33] Domain Mapping: Map alert topic to stakeholder domain
        topic_to_domain = {
            "energy_resource_risk": "energy",
            "global_market_intelligence": "market",
            "ai_semiconductor_intelligence": "ai_semi",
            "crypto_geopolitics": "crypto",
            "defense_technology": "defense",
            "supply_chain_intelligence": "supply_chain"
        }
        # Inferred from title/summary if topic is missing
        target_domain = topic_to_domain.get(title.lower(), "global")
        if target_domain == "global":
            # Fallback check against known keywords in title
            for key, val in topic_to_domain.items():
                if val in title.lower() or val in summary.lower():
                    target_domain = val
                    break

        logger.info(f"[Antigravity] Injecting Context for Domain: {target_domain}")
        known_stakes = await self.get_top_stakeholders(limit=15, domain=target_domain)
        
        stakeholder_context = []
        for s in known_stakes:
            indices = await ImpactCalculator.evaluate_sociographic_indices(self.db, s.id)
            stakeholder_context.append({
                "id": str(s.id),
                "name": s.name,
                "domain": s.domain,
                "quantum_indices": indices
            })

        logger.info(f"[Antigravity] Quantum Baseline Injected: {len(stakeholder_context)} entities analyzed.")
        if stakeholder_context:
            logger.info(f"[Antigravity] Sample Baseline: {stakeholder_context[0]['name']} -> {stakeholder_context[0]['quantum_indices']}")

        system_prompt = (
            "You are an OSINT Intelligence Architect. Your task is to analyze cascading ripple effects "
            "as a DIVERGENT BRANCHING CAUSAL TREE (Order 1 -> Order 2 -> Order 3).\n\n"
            "CONTEXTUAL DATA: You are provided with SOCIOGRAPHIC INDICATORS for known stakeholders:\n"
            "- Resilience (Omega): Ability to substitute/recover. Lower = more vulnerable.\n"
            "- Contagion (Delta-C): Probability of impact transfer to next node.\n"
            "- Fragility (FRG): Structural vulnerability from concentrated dependencies.\n\n"
            "COGNITIVE DIRECTIVES:\n"
            "1. METRIC-DRIVEN JUSTIFICATION: In 'reasoning', EXPLICITLY cite the Omega/Delta-C values from the context to explain the magnitude. e.g. 'Given a low Omega of 35%, disruption is expected to persist over 2 weeks.'\n"
            "2. ACTIONABLE ADVICE: For every finding, provide a specific 'containment_action'.\n"
            "3. TIMELINE: Estimate 'time_to_impact' (e.g., 'Immediate', '3-5 Days', '2-4 Weeks').\n"
            "4. CASCADING RIPPLE EFFECTS (MANDATORY): For every finding, identify AT LEAST ONE secondary cascading impact. "
            "e.g. If TSMC is Order 1, Order 2 could be Apple or NVIDIA semiconductor shortages. "
            "Link your discovery where possible to the Known Stakeholders provided.\n"
            "5. FAN-OUT: Identify 3 distinct Level 1 entities, and branch level 2 for each.\n"
            "5. GEO-ENRICHMENT: For each entity (ESPECIALLY unknown ones not in the context list), "
            "provide 'entity_lat', 'entity_lng' (decimal degrees), 'entity_sector', and 'entity_country'.\n\n"
            "Strictly return nested branching JSON with this exact schema:\n"
            "{\n"
            "  'findings': [\n"
            "    {\n"
            "      'entity_name': 'Company or Region Name',\n"
            "      'entity_lat': 35.68,\n"
            "      'entity_lng': 139.69,\n"
            "      'entity_sector': 'semiconductor',\n"
            "      'entity_country': 'Japan',\n"
            "      'impact_alpha': -5.0,\n"
            "      'impact_summary': '3-5 word summary',\n"
            "      'reasoning': 'Cite Omega/Delta-C values here to justify magnitude.',\n"
            "      'containment_action': 'Specific actionable recommendation.',\n"
            "      'time_to_impact': 'Estimated timeline',\n"
            "      'cascading_impacts': [...same schema...]\n"
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
            analysis_raw = await generate_analysis(system_prompt, user_prompt, is_batch=False)
            analysis = {}
            if isinstance(analysis_raw, str):
                import re
                # Robustly find JSON block in case LLM adds conversational text
                match = re.search(r'\{.*\}', analysis_raw, re.DOTALL)
                if match:
                    try:
                        analysis = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        logger.error("Failed to parse JSON from LLM response.")
            elif isinstance(analysis_raw, dict):
                analysis = analysis_raw

            findings = analysis.get("findings", [])
            
            # [v10.9] Statistical Fallback: If AI is empty or degraded, use numerical model
            if not findings:
                logger.info(f"AI returned empty findings for {title}. Triggering Statistical Fallback.")
                from processor.impact_calculator import ImpactCalculator
                findings = ImpactCalculator.calculate_impacts(
                    topic=summary.split(' ')[0],
                    lat=None, lng=None, 
                    intensity=5.0
                )

            async def enrich_finding(finding: Dict[str, Any]):
                """Enrich finding with DB data, auto-provisioning new entities as needed."""
                if "source" not in finding:
                    finding["source"] = "ai_reasoning"
                
                s_id = finding.get("stakeholder_id")
                stakeholder = None
                
                try:
                    # 1. Attempt exact ID match
                    if s_id and s_id != "null":
                        s_stmt = select(Stakeholder).where(Stakeholder.id == uuid.UUID(s_id))
                        stakeholder = (await self.db.execute(s_stmt)).scalar_one_or_none()
                    
                    # 2. [v10.21] Backbone-priority fuzzy name match
                    if not stakeholder and finding.get("entity_name"):
                        # Prefer backbone (is_auto_provisioned=False) entities first
                        fuzzy_stmt = select(Stakeholder).where(
                            Stakeholder.name.ilike(f"%{finding['entity_name']}%")
                        ).order_by(Stakeholder.is_auto_provisioned.asc())  # False (backbone) comes first
                        result = (await self.db.execute(fuzzy_stmt)).first()
                        if result:
                            stakeholder = result[0]

                    # 3. [v10.19] AUTO-PROVISIONING: If still not found, create new tactical node
                    if not stakeholder:
                        stakeholder = await self._auto_provision_stakeholder(finding)

                    if stakeholder:
                        finding["stakeholder_id"] = str(stakeholder.id)
                        finding["location_lat"] = stakeholder.location_lat
                        finding["location_lng"] = stakeholder.location_lng

                        # [v10.21] Activity tracking: update hit statistics
                        stakeholder.hit_count = (stakeholder.hit_count or 0) + 1
                        stakeholder.last_hit_at = datetime.now(timezone.utc)
                        # Re-calc Indices (may be zero if just created, will grow over time)
                        indices = await ImpactCalculator.evaluate_sociographic_indices(self.db, stakeholder.id)
                        finding["quantum_metrics"] = indices

                        # Create Prediction record for self-learning
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
                        # Final fallback: probabilistic estimation
                        finding["quantum_metrics"] = {
                            "resilience": 45.0, 
                            "contagion": 0.4, 
                            "fragility": 0.5,
                            "metrics_source": "probabilistic_estimation"
                        }
                except Exception as ex:
                    logger.warning(f"Failed to enrich stakeholder '{finding.get('entity_name')}': {ex}")

                # Recurse into children (Serial to avoid Session concurrency issues)
                children = finding.get("cascading_impacts", [])
                for child in children:
                    await enrich_finding(child)

            processed_findings = []
            # Serial enrichment across all top-level findings
            for f in findings:
                await enrich_finding(f)
                processed_findings.append(f)

            await self.db.commit()
            
            # Store in Cache
            _discovery_cache[event_hash] = (datetime.now(timezone.utc), processed_findings)

            # [v10.29] INTERNAL DB UPDATE: If alert_id provided, persist status and results
            if alert_id:
                from db.models import AlertLog
                stmt = select(AlertLog).where(AlertLog.id == alert_id)
                alert = (await self.db.execute(stmt)).scalar_one_or_none()
                if alert:
                    meta = dict(alert.metadata_json) if alert.metadata_json else {}
                    meta["cascading_impacts"] = processed_findings
                    meta["backbone_discovery_status"] = "complete"
                    meta["backbone_discovery_ts"] = datetime.now(timezone.utc).isoformat()
                    alert.metadata_json = meta
                    flag_modified(alert, "metadata_json")
                    await self.db.commit()
                    logger.info(f"[Antigravity] Background analysis persisted for Alert {alert_id}")
            
            return processed_findings

        except Exception as e:
            logger.error(f"Error in ImpactDiscoveryEngine: {e}")
            await self.db.rollback()
            return []
