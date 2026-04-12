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
        """
        Calculate Quantitative Baseline for a specific stakeholder.
        - Omega (Resilience Factor)
        - Delta-C (Contagion Probability)
        - FRG (Fragility Index)
        """
        try:
            # Fetch dependencies where this stakeholder is a source or target
            stmt = select(Dependency).where(
                (Dependency.source_id == stakeholder_id) | (Dependency.target_id == stakeholder_id)
            )
            result = await db.execute(stmt)
            deps = result.scalars().all()
            
            if not deps:
                return {
                    "resilience": 50.0,
                    "contagion": 0.3,
                    "fragility": 0.4,
                    "metrics_source": "sector_baseline"
                }

            # 1. Resilience Factor (Omega): Higher substitution_elasticity = Higher resilience
            avg_elasticity = sum(d.substitution_elasticity for d in deps) / len(deps)
            resilience = round(avg_elasticity * 100, 1)

            # 2. Contagion Prob (Delta-C): beta_correlation * exposure_weight
            source_deps = [d for d in deps if d.source_id == stakeholder_id]
            if source_deps:
                avg_contagion = sum(d.beta_correlation * d.exposure_weight for d in source_deps) / len(source_deps)
            else:
                avg_contagion = 0.3
            contagion = round(avg_contagion, 2)

            # 3. Fragility Index (FRG): Dependence on single sources
            inbound_deps = [d for d in deps if d.target_id == stakeholder_id]
            fragility = round(len(inbound_deps) * 0.15 + (1 - avg_elasticity), 2)

            return {
                "resilience": resilience,
                "contagion": min(1.0, contagion),
                "fragility": min(1.0, fragility),
                "metrics_source": "graph_tensor"
            }
        except Exception as e:
            logger.error(f"Failed to calculate indices for {stakeholder_id}: {e}")
            return {"resilience": 50, "contagion": 0.5, "fragility": 0.5, "metrics_source": "fallback"}

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
