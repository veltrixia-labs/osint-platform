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
            async with asyncio.timeout(300):
                # 1. Context Preparation
                known_stakes = await self._get_strategic_context(title, summary, alert_id)
                stakeholder_context = []
                from processor.impact_calculator import ImpactCalculator
                # Note: evaluate_bulk_indices is now preferred
                indices_map = await ImpactCalculator.evaluate_bulk_indices(self.db, [s.id for s in known_stakes])
                for s in known_stakes:
                    stakeholder_context.append({"name": s.name, "domain": s.domain, "quantum_indices": indices_map.get(s.id)})

                # 2. AI Analytical Phase
                system_prompt = self._get_system_prompt()
                user_prompt = f"SIGNAL: {title}\nSUMMARY: {summary}\nCONTEXT:\n{json.dumps(stakeholder_context, indent=2)}"
                
                analysis_raw = await generate_analysis(system_prompt, user_prompt, is_batch=False)
                analysis = self._parse_llm_json(analysis_raw)
                findings = analysis.get("findings", [])

                if not findings:
                    logger.info("Triggering Statistical Fallback.")
                    findings = ImpactCalculator.calculate_impacts(summary.split(' ')[0], None, None, 5.0)

                # 3. BATCH ENRICHMENT
                processed_findings = await self._enrich_findings_batch(findings)

                # 4. Atomic Terminal Persistence
                if alert_id:
                    await self._persist_terminal_state(alert_id, processed_findings, "complete")
                
                _discovery_cache[event_hash] = (datetime.now(timezone.utc), processed_findings)
                return processed_findings

        except (asyncio.TimeoutError, TimeoutError):
            logger.error(f"[Batch Stall] Analysis timed out for {alert_id}.")
            if alert_id: await self._persist_terminal_state(alert_id, [], "failed")
            return []
        except Exception as e:
            logger.error(f"Critical Fault in Batch Pipeline: {e}")
            if alert_id: await self._persist_terminal_state(alert_id, [], "failed")
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
        """[v11.5] High-Efficiency Batch Enrichment."""
        from processor.impact_calculator import ImpactCalculator
        
        # 1. Flatten tree to find all unique entity names
        entities_to_resolve = set()
        def collect(fs):
            for f in fs:
                if f.get("entity_name"): entities_to_resolve.add(f["entity_name"].lower())
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

        # 3. Bulk Index Calculation (The true efficiency winner)
        stakeholder_ids = [s.id for s in registry.values()]
        indices_map = await ImpactCalculator.evaluate_bulk_indices(self.db, stakeholder_ids)

        # 4. In-Memory Decoration
        def decorate(fs):
            for f in fs:
                name = f.get("entity_name", "").lower()
                s = registry.get(name)
                if s:
                    f["stakeholder_id"] = str(s.id)
                    f["quantum_metrics"] = indices_map.get(s.id)
                else:
                    f["quantum_metrics"] = {"resilience": 50, "contagion": 0.4, "metrics_source": "probabilistic"}
                decorate(f.get("cascading_impacts", []))

        decorate(findings)
        return findings

    async def _persist_terminal_state(self, alert_id: uuid.UUID, findings: list, status: str):
        try:
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
                logger.info(f"[Discovery] Alert {alert_id} terminal state -> {status}")
        except Exception as e:
            logger.error(f"Failed to persist terminal state: {e}")

    @classmethod
    async def run_discovery_scout(cls):
        """[v13.0] Autonomous Scout: Rescues stuck alerts and processes pending discovery."""
        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            try:
                # 1. Rescue Phase: Reset alerts stuck in 'processing' for > 10 mins
                threshold = datetime.now(timezone.utc) - timedelta(minutes=10)
                stmt = select(AlertLog).where(AlertLog.triggered_at > (datetime.now(timezone.utc) - timedelta(hours=6)))
                res = await session.execute(stmt)
                all_recent = res.scalars().all()
                
                rescue_count = 0
                for a in all_recent:
                    meta = dict(a.metadata_json) if a.metadata_json else {}
                    if meta.get("backbone_discovery_status") == "processing":
                        ts_str = meta.get("backbone_discovery_ts")
                        if ts_str:
                            try:
                                ts = datetime.fromisoformat(ts_str)
                                if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                                if datetime.now(timezone.utc) - ts > timedelta(minutes=10):
                                    logger.warning(f"[Scout] Rescuing stuck alert {a.id} (Started: {ts_str})")
                                    meta["backbone_discovery_status"] = "failed"
                                    a.metadata_json = meta
                                    flag_modified(a, "metadata_json")
                                    rescue_count += 1
                            except: pass
                
                if rescue_count > 0:
                    await session.commit()
                    logger.info(f"[Scout] Rescue complete. {rescue_count} alerts reset to 'failed'.")

                # 2. Discovery Phase: Pick up pending/failed alerts
                stmt = select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(25)
                res = await session.execute(stmt)
                alerts = res.scalars().all()
                
                scout_count = 0
                for a in alerts:
                    meta = a.metadata_json or {}
                    status = meta.get("backbone_discovery_status", "idle")
                    
                    if status in ["idle", "failed"] and scout_count < 5:
                        logger.info(f"[Scout] Processing alert {a.id} (Status: {status})")
                        meta["backbone_discovery_status"] = "processing"
                        meta["backbone_discovery_ts"] = datetime.now(timezone.utc).isoformat()
                        a.metadata_json = meta
                        flag_modified(a, "metadata_json")
                        await session.commit()
                        
                        engine = ImpactDiscoveryEngine(session)
                        title = a.target_label
                        summary = meta.get("description", f"Triggered on {a.topic}")
                        await engine.run_discovery(uuid.uuid4(), title, summary, a.id)
                        scout_count += 1
            except Exception as e:
                logger.error(f"[Scout] Execution failed: {e}")
