import math
import logging
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Stakeholder, Dependency

logger = logging.getLogger(__name__)

# Topics to Strategic Asset Mapping (Canonical Bridges)
TOPIC_ASSET_MAP = {
    "energy_resource_risk": ["hormuz", "aramco_hq", "gazprom_hq", "suez", "bab_el_mandeb"],
    "global_market_intelligence": ["nyse", "fed", "ecb_hq", "jpm_hq", "gs_hq", "swift"],
    "ai_semiconductor_intelligence": ["nvda_hq", "tsmc_hq", "asml_hq", "samsung_px", "intel_or"],
    "defense_technology": ["lmt_hq", "pltr_hq", "bae_hq", "andersen_afb", "spacex_hq"],
    "supply_chain_intelligence": ["suez", "malacca", "panama_canal", "maersk_hq", "dp_world"],
    "crypto_geopolitics": ["binance_hub", "tether_hub", "coinbase_hq", "circle_hq", "mstr_hq"],
    "global": ["swift", "fed", "suez", "malacca"]
}

class ImpactCalculator:
    """
    [v10.18] Quantum Analytics Engine.
    Calculates sociological and statistical indices to inform AI predictions.
    """
    
    @staticmethod
    async def evaluate_sociographic_indices(db: AsyncSession, stakeholder_id: uuid.UUID) -> Dict[str, Any]:
        """[Legacy] Single-ID wrapper for compatibility."""
        results = await ImpactCalculator.evaluate_bulk_indices(db, [stakeholder_id])
        return results.get(stakeholder_id, {
            "resilience": 50.0, "contagion": 0.3, "fragility": 0.4, "metrics_source": "fallback"
        })

    @staticmethod
    async def evaluate_bulk_indices(db: AsyncSession, stakeholder_ids: List[uuid.UUID]) -> Dict[uuid.UUID, Dict[str, Any]]:
        """
        [v11.0.0] Bulk Quantum Analytics.
        Calculates indices for multiple stakeholders in a single pass.
        """
        if not stakeholder_ids: return {}
        try:
            # 1. Fetch ALL relevant dependencies
            stmt = select(Dependency).where(
                or_(
                    Dependency.source_id.in_(stakeholder_ids),
                    Dependency.target_id.in_(stakeholder_ids)
                )
            )
            result = await db.execute(stmt)
            all_deps = result.scalars().all()
            
            # 2. Group by stakeholder
            lookup = {sid: {"indices": [], "source_deps": [], "inbound_deps": []} for sid in stakeholder_ids}
            for d in all_deps:
                if d.source_id in lookup:
                    lookup[d.source_id]["indices"].append(d)
                    lookup[d.source_id]["source_deps"].append(d)
                if d.target_id in lookup:
                    lookup[d.target_id]["indices"].append(d)
                    lookup[d.target_id]["inbound_deps"].append(d)

            # 3. Calculate for each
            final_results = {}
            for sid in stakeholder_ids:
                data = lookup[sid]
                deps = data["indices"]
                if not deps:
                    final_results[sid] = {
                        "resilience": 50.0, "contagion": 0.3, "fragility": 0.4, "metrics_source": "sector_baseline"
                    }
                    continue

                avg_elasticity = sum(d.substitution_elasticity for d in deps) / len(deps)
                source_deps = data["source_deps"]
                avg_contagion = sum(d.beta_correlation * d.exposure_weight for d in source_deps) / len(source_deps) if source_deps else 0.3
                inbound_deps = data["inbound_deps"]
                fragility = len(inbound_deps) * 0.15 + (1 - avg_elasticity)

                final_results[sid] = {
                    "resilience": round(avg_elasticity * 100, 1),
                    "contagion": min(1.0, round(avg_contagion, 2)),
                    "fragility": min(1.0, round(fragility, 2)),
                    "metrics_source": "graph_tensor"
                }

            return final_results
        except Exception as e:
            logger.error(f"Bulk indices calculation failed: {e}")
            return {sid: {"resilience": 50, "contagion": 0.5, "fragility": 0.5, "metrics_source": "fallback"} for sid in stakeholder_ids}

    @staticmethod
    def calculate_impacts(topic: str, lat: Optional[float], lng: Optional[float], intensity: float) -> List[Dict[str, Any]]:
        """Fallback engine when AI is unavailable."""
        findings = []
        target_keys = TOPIC_ASSET_MAP.get(topic, TOPIC_ASSET_MAP["global"])
        
        chain = []
        for i, asset_id in enumerate(target_keys[:3]):
            target_name = asset_id.replace("_", " ").title()
            attenuation = 1.0 / (1.0 + (i * 0.5))
            calculated_alpha = round(-(intensity * 0.5) * attenuation, 2)
            
            chain.append({
                "stakeholder_id": None,
                "entity_name": target_name,
                "impact_direction": "negative",
                "impact_alpha": calculated_alpha,
                "confidence": 0.7 - (i * 0.1),
                "reasoning": f"Level {i+1} propagation: Volatility transfer from preceding node in {topic} sector.",
                "source": "statistical_model",
                "cascading_impacts": []
            })

        if len(chain) >= 3:
            chain[1]["cascading_impacts"] = [chain[2]]
            chain[0]["cascading_impacts"] = [chain[1]]
            findings = [chain[0]]
        elif len(chain) > 0:
            findings = [chain[0]]
            
        return findings
