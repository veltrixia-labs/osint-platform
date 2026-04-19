import asyncio
import logging
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from sqlalchemy.orm.attributes import flag_modified
from db.models import Stakeholder, Dependency, AlertLog
from llm.client import generate_analysis

logger = logging.getLogger(__name__)

# Global Discovery Cache to preserve LLM quota
_discovery_cache = {}
CACHE_TTL_HOURS = 6

class ImpactDiscoveryEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_top_stakeholders(self, limit: int = 15, domain: Optional[str] = None, exclude_domain: Optional[str] = None) -> List[Stakeholder]:
        stmt = select(Stakeholder)
        STRATEGIC_DOMAINS = ["energy", "market", "crypto", "ai_semi", "defense", "supply_chain"]
        
        if domain and domain != "global":
            stmt = stmt.where(Stakeholder.domain == domain)
        elif exclude_domain:
            stmt = stmt.where(Stakeholder.domain.in_(STRATEGIC_DOMAINS))
            stmt = stmt.where(Stakeholder.domain != exclude_domain)
            
        stmt = stmt.order_by(Stakeholder.strategic_score.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def run_discovery(self, trigger_item_id: uuid.UUID, title: str, summary: str, alert_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
        import hashlib
        event_hash = hashlib.md5(f"{title}:{summary[:100]}".encode()).hexdigest()
        cached_result = _discovery_cache.get(event_hash)
        if cached_result:
            ts, data = cached_result
            if datetime.now(timezone.utc) - ts < timedelta(hours=CACHE_TTL_HOURS):
                logger.info(f"Using cached impact discovery for event hash: {event_hash}")
                return data

        try:
            # [v10.60] BATCH RATIONALIZATION PIPELINE
            # Wrap entire process in a single high-level timeout
            async with asyncio.timeout(300):
                # 1. Context Preparation
                known_stakes = await self._get_strategic_context(title, summary, alert_id)
                stakeholder_context = []
                from processor.impact_calculator import ImpactCalculator
                for s in known_stakes:
                    indices = await ImpactCalculator.evaluate_sociographic_indices(self.db, s.id)
                    stakeholder_context.append({"name": s.name, "domain": s.domain, "quantum_indices": indices})

                # 2. AI Analytical Phase (Single Call)
                system_prompt = self._get_system_prompt()
                user_prompt = f"SIGNAL: {title}\nSUMMARY: {summary}\nCONTEXT:\n{json.dumps(stakeholder_context, indent=2)}"
                
                analysis_raw = await generate_analysis(system_prompt, user_prompt, is_batch=False)
                analysis = self._parse_llm_json(analysis_raw)
                findings = analysis.get("findings", [])

                if not findings:
                    logger.info("Triggering Statistical Fallback.")
                    findings = ImpactCalculator.calculate_impacts(summary.split(' ')[0], None, None, 5.0)

                # 3. BATCH ENRICHMENT (RATIONALIZED)
                # No more parallel recursive DB commits. Processing in-memory one pass.
                processed_findings = await self._enrich_findings_batch(findings)

                # 4. Atomic Terminal Persistence
                if alert_id:
                    await self._persist_terminal_state(alert_id, processed_findings, "complete")
                
                _discovery_cache[event_hash] = (datetime.now(timezone.utc), processed_findings)
                return processed_findings

        except (asyncio.TimeoutError, TimeoutError):
            logger.error(f"[Batch Stall] Analysis timed out for {alert_id}. Falling back to empty/partial.")
            if alert_id:
                await self._persist_terminal_state(alert_id, [], "failed")
            return []
        except Exception as e:
            logger.error(f"Critical Fault in Batch Pipeline: {e}")
            if alert_id:
                await self._persist_terminal_state(alert_id, [], "failed")
            return []

    async def _get_strategic_context(self, title: str, summary: str, alert_id: Optional[uuid.UUID]):
        topic_to_domain = {
            "energy_resource_risk": "energy", "global_market_intelligence": "market",
            "ai_semiconductor_intelligence": "ai_semi", "crypto_geopolitics": "crypto",
            "defense_technology": "defense", "supply_chain_intelligence": "supply_chain"
        }
        target_domain = "global"
        if alert_id:
            res = await self.db.execute(select(AlertLog).where(AlertLog.id == alert_id))
            alert = res.scalar_one_or_none()
            if alert: target_domain = topic_to_domain.get(alert.topic, "global")
        
        local = await self.get_top_stakeholders(limit=7, domain=target_domain)
        anchors = await self.get_top_stakeholders(limit=8, exclude_domain=target_domain)
        return local + anchors

    def _get_system_prompt(self):
        return (
            "You are a Strategic OSINT Architect. Analyze cascading ripple effects as a DIVERGENT BRANCHING CAUSAL TREE.\n"
            "Focus on Strategic Sectors: Energy, Market, Crypto, AI/Semi, Defense, Supply Chain.\n"
            "Strictly return nested JSON: { 'findings': [{ 'entity_name', 'entity_lat', 'entity_lng', 'entity_sector', 'impact_alpha', 'reasoning', 'cascading_impacts': [...] }] }"
        )

    def _parse_llm_json(self, raw):
        if isinstance(raw, dict): return raw
        if isinstance(raw, str):
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try: return json.loads(match.group(0))
                except: pass
        return {}

    async def _enrich_findings_batch(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """[v10.60] The Core Batch Logic: Resolve all stakeholders in ONE PASS."""
        # 1. Flatten tree to find all unique entity names
        entities_to_resolve = set()
        def collect(fs):
            for f in fs:
                if f.get("entity_name"): entities_to_resolve.add(f["entity_name"])
                collect(f.get("cascading_impacts", []))
        collect(findings)

        # 2. Bulk Resolve Stakeholders
        registry = {}
        if entities_to_resolve:
            filters = [Stakeholder.name.ilike(f"%{name}%") for name in entities_to_resolve]
            stmt = select(Stakeholder).where(or_(*filters))
            res = await self.db.execute(stmt)
            for s in res.scalars().all():
                registry[s.name.lower()] = s

        # 3. In-Memory Decoration (No DB calls)
        from processor.impact_calculator import ImpactCalculator
        async def decorate(fs):
            for f in fs:
                name = f.get("entity_name", "").lower()
                s = registry.get(name)
                if s:
                    f["stakeholder_id"] = str(s.id)
                    f["quantum_metrics"] = await ImpactCalculator.evaluate_sociographic_indices(self.db, s.id)
                else:
                    f["quantum_metrics"] = {"resilience": 50, "contagion": 0.4, "metrics_source": "probabilistic"}
                await decorate(f.get("cascading_impacts", []))

        await decorate(findings)
        return findings

    async def _persist_terminal_state(self, alert_id: uuid.UUID, findings: list, status: str):
        """Atomic terminal update. Minimal lock window."""
        try:
            # Note: Using session from __init__ if possible, or new one for isolation
            # For simplicity, we use the engine's current session but we could use a local one.
            stmt = select(AlertLog).where(AlertLog.id == alert_id)
            res = await self.db.execute(stmt)
            alert = res.scalar_one_or_none()
            if alert:
                meta = dict(alert.metadata_json) if alert.metadata_json else {}
                if findings: meta["cascading_impacts"] = findings
                meta["backbone_discovery_status"] = status
                meta["backbone_discovery_ts"] = datetime.now(timezone.utc).isoformat()
                alert.metadata_json = meta
                flag_modified(alert, "metadata_json")
                await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to persist terminal state: {e}")
