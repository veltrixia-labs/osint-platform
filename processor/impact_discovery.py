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

# Global Lock for Alert Metadata to prevent parallel overwrites during streaming
_meta_lock = asyncio.Lock()

class ImpactDiscoveryEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_top_stakeholders(self, limit: int = 15, domain: Optional[str] = None, exclude_domain: Optional[str] = None) -> List[Stakeholder]:
        stmt = select(Stakeholder)
        
        # [v10.37] STRATEGIC THINK-TANK CALIBRATION
        STRATEGIC_DOMAINS = ["energy", "market", "crypto", "ai_semi", "defense", "supply_chain"]
        
        if domain and domain != "global":
            stmt = stmt.where(Stakeholder.domain == domain)
        elif exclude_domain:
            # Pull 'anchors' from across the strategic spectrum to encourage cross-sector analysis
            stmt = stmt.where(Stakeholder.domain.in_(STRATEGIC_DOMAINS))
            stmt = stmt.where(Stakeholder.domain != exclude_domain)
            
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
        # --- Topic Resolution [v10.36] ---
        target_domain = "global"
        
        # 1. Attempt lookup if alert_id is provided
        from db.models import AlertLog
        alert_topic = None
        if alert_id:
            stmt = select(AlertLog).where(AlertLog.id == alert_id)
            alert = (await self.db.execute(stmt)).scalar_one_or_none()
            if alert:
                alert_topic = alert.topic
        
        # 2. Map topic to domain
        if alert_topic:
            target_domain = topic_to_domain.get(alert_topic, "global")
        else:
            # Fallback to Title/Summary inference if no alert_id or no topic
            for key, val in topic_to_domain.items():
                if val in title.lower() or val in summary.lower():
                    target_domain = val
                    break

        # [v10.37] DYNAMIC CROSS-SECTOR CONTEXT
        # We pull 7 stakeholders from the target domain (Local Focus)
        # And 8 stakeholders from across ALL other domains (Strategic Anchors)
        # This ensures the AI can discover cross-sector ripples (e.g. Energy -> Trade).
        logger.info(f"[Antigravity] Injecting Dynamic Strategic Context for Domain: {target_domain}")
        
        local_stakes = await self.get_top_stakeholders(limit=7, domain=target_domain)
        anchor_stakes = await self.get_top_stakeholders(limit=8, exclude_domain=target_domain)
        
        known_stakes = local_stakes + anchor_stakes
        
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
            "You are an OSINT Strategic Intelligence Architect for a high-fidelity Think Tank. "
            "Your task is to analyze cascading ripple effects as a DIVERGENT BRANCHING CAUSAL TREE.\n\n"
            "STRATEGIC SCOPE (MANDATORY):\n"
            "You focus ONLY on 6 strategic sectors: Energy, Markets, Crypto, AI/Semiconductors, Defense, and Supply Chain/Trade.\n"
            "Exclude general news, celebrity gossip, or localized events without global strategic significance.\n\n"
            "CONTEXTUAL DATA: You are provided with SOCIOGRAPHIC INDICATORS for known Strategic Backbone Entities:\n"
            "- Resilience (Omega): Ability to substitute/recover. Lower = more vulnerable.\n"
            "- Contagion (Delta-C): Probability of impact transfer to next node.\n"
            "- Fragility (FRG): Structural vulnerability from concentrated dependencies.\n\n"
            "COGNITIVE DIRECTIVES:\n"
            "1. MASTER PIVOT ANALYSIS: Use the provided Backbone Entities as 'Connective Hubs'. "
            "e.g. If an Energy risk occurs, analyze how it pivots into the 'Trade' sector via specific Backbone shipping ports or 'Market' sectors via energy-indexed funds.\n"
            "2. METRIC-DRIVEN JUSTIFICATION: In 'reasoning', EXPLICITLY cite the Omega/Delta-C values from the context. "
            "e.g. 'Given TSMC's Fragility (FRG) of 0.85, this localized technical failure poses a systemic contagion risk to the global AI sector.'\n"
            "3. ACTIONABLE ADVICE: For every finding, provide an OSINT-grade 'containment_action'.\n"
            "4. CASCADING RIPPLE EFFECTS: For every finding, identify AT LEAST ONE secondary cascading impact. "
            "Link findings where possible to the Known Backbone Stakeholders provided.\n"
            "5. GEO-ENRICHMENT: For each entity (especially unknown ones), provide 'entity_lat', 'entity_lng', 'entity_sector', and 'entity_country'.\n\n"
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

            # [v10.45] HIGH-FIDELITY PARALLEL PIPELINE
            import asyncio
            from db.database import AsyncSessionLocal
            
            # Use Semaphore to avoid DB connection exhaustion
            semaphore = asyncio.Semaphore(5)
            global_visited = set()

            # [v10.50] Global Timeout Protection: Ensure a single alert never stalls the pipeline
            async with asyncio.timeout(300): # 5 min total budget per alert Analysis
                async def parallel_enrich(finding: Dict[str, Any]):
                    async with semaphore:
                        # [v10.50] Isolated Session: Session created OUTSIDE of any metadata locks
                        async with AsyncSessionLocal() as branch_session:
                            try:
                                # Re-initialize engine with local session for safety
                                branch_engine = ImpactDiscoveryEngine(branch_session)
                                # [v10.50] Individual timeout for LLM branch refinement
                                await asyncio.wait_for(
                                    branch_engine._enrich_finding_recursive(finding, 1, global_visited),
                                    timeout=120
                                )
                                
                            return finding 

            # Phase 1: AI Reasoning (Completed above)
            # Phase 2: Parallel Graph Enrichment
            if findings:
                tasks = [parallel_enrich(f) for f in findings]
                completed = await asyncio.gather(*tasks)
                processed_findings = [c for c in completed if c]
            else:
                processed_findings = []

            # Store in Cache
            _discovery_cache[event_hash] = (datetime.now(timezone.utc), processed_findings)

            # [v10.36] TERMINAL STATE PERSISTENCE
            if alert_id:
                await self._persist_final_state(alert_id, processed_findings, "complete")
            
            return processed_findings

        except Exception as e:
            logger.error(f"CRITICAL FAULT in ImpactDiscoveryEngine: {e}")
            if alert_id:
                await self._persist_final_state(alert_id, [], "failed")
            return []

    async def _enrich_finding_recursive(self, finding: Dict[str, Any], depth: int, visited_entities: set):
        """
        Internal recursive worker for high-fidelity enrichment.
        """
        if depth > 4:
            finding["cascading_impacts"] = []
            return

        entity_name = finding.get("entity_name", "Unknown")
        # Robust node ID
        e_lat = finding.get("entity_lat", finding.get("location_lat", "0"))
        e_lng = finding.get("entity_lng", finding.get("location_lng", "0"))
        node_id = f"{entity_name}:{e_lat}:{e_lng}"
        
        if node_id in visited_entities:
            finding["cascading_impacts"] = []
            return
        visited_entities.add(node_id)

        try:
            from processor.impact_calculator import ImpactCalculator
            s_id = finding.get("stakeholder_id")
            stakeholder = None
            
            # 1. DB Lookup
            if s_id and s_id != "null":
                try:
                    stmt = select(Stakeholder).where(Stakeholder.id == uuid.UUID(s_id))
                    stakeholder = (await self.db.execute(stmt)).scalar_one_or_none()
                except: pass
            
            if not stakeholder and entity_name != "Unknown":
                fuzzy_stmt = select(Stakeholder).where(Stakeholder.name.ilike(f"%{entity_name}%")).order_by(Stakeholder.is_auto_provisioned.asc())
                res = await self.db.execute(fuzzy_stmt)
                stakeholder = res.scalars().first()

            # 2. Provisioning
            if not stakeholder:
                stakeholder = await self._auto_provision_stakeholder(finding)

            # 3. Metrics Calculation
            if stakeholder:
                finding["stakeholder_id"] = str(stakeholder.id)
                finding["location_lat"] = stakeholder.location_lat
                finding["location_lng"] = stakeholder.location_lng
                finding["entity_name"] = stakeholder.name
                
                indices = await ImpactCalculator.evaluate_sociographic_indices(self.db, stakeholder.id)
                finding["quantum_metrics"] = indices
                
                stakeholder.hit_count = (stakeholder.hit_count or 0) + 1
                stakeholder.last_hit_at = datetime.now(timezone.utc)
                await self.db.commit()
            else:
                finding["quantum_metrics"] = {"resilience": 50, "contagion": 0.4, "metrics_source": "probabilistic"}

            # 4. Recursion into next wave (breadth-first-within-serial-recursion for clarity)
            children = finding.get("cascading_impacts", [])
            if children:
                for child in children:
                    await self._enrich_finding_recursive(child, depth + 1, visited_entities)

        except Exception as ex:
            logger.warning(f"Branch enrichment stalled for {entity_name}: {ex}")

    async def _persist_final_state(self, alert_id: uuid.UUID, findings: list, status: str):
        """Atomic update of the alert metadata to terminal or partial states."""
        try:
            from db.database import AsyncSessionLocal
            from db.models import AlertLog
            # [v10.50] Session OUTSIDE lock to avoid connection pool deadlock
            async with AsyncSessionLocal() as session:
                async with _meta_lock:
                    stmt = select(AlertLog).where(AlertLog.id == alert_id)
                    alert = (await session.execute(stmt)).scalar_one_or_none()
                    if alert:
                        meta = dict(alert.metadata_json) if alert.metadata_json else {}
                        if findings:
                            meta["cascading_impacts"] = findings
                        meta["backbone_discovery_status"] = status
                        meta["backbone_discovery_ts"] = datetime.now(timezone.utc).isoformat()
                        alert.metadata_json = meta
                        flag_modified(alert, "metadata_json")
                        await session.commit()
                        logger.info(f"[Antigravity] Alert {alert_id} state -> {status}")
        except Exception as e:
            logger.error(f"Failed to persist state for alert {alert_id}: {e}")

    async def _append_partial_discovery(self, alert_id: uuid.UUID, finding: Dict[str, Any]):
        """Append a single finding branch to the AlertLog in real-time with lock protection."""
        try:
            from db.database import AsyncSessionLocal
            from db.models import AlertLog
            # [v10.50] Session OUTSIDE lock to avoid connection pool deadlock
            async with AsyncSessionLocal() as session:
                async with _meta_lock:
                    stmt = select(AlertLog).where(AlertLog.id == alert_id)
                    alert = (await session.execute(stmt)).scalar_one_or_none()
                    if alert:
                        meta = dict(alert.metadata_json) if alert.metadata_json else {}
                        impacts = meta.get("cascading_impacts", [])
                        # Append or Update finding (avoiding duplicates)
                        match_idx = next((i for i, f in enumerate(impacts) if f.get('entity_name') == finding.get('entity_name')), -1)
                        if match_idx >= 0:
                            impacts[match_idx] = finding
                        else:
                            impacts.append(finding)
                        
                        meta["cascading_impacts"] = impacts
                        alert.metadata_json = meta
                        flag_modified(alert, "metadata_json")
                        await session.commit()
        except Exception as e:
            logger.error(f"Failed to append partial discovery: {e}")
