import math
import logging
from typing import List, Dict, Any, Optional

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

def get_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class ImpactCalculator:
    """Mathematical fallback engine for calculating probabilistic impacts when AI is unavailable."""
    
    @staticmethod
    def calculate_impacts(topic: str, lat: Optional[float], lng: Optional[float], intensity: float) -> List[Dict[str, Any]]:
        from db.models import Stakeholder # Lazy import to avoid circular dep
        # For simplicity in this demo, we'll simulate the finding structure based on TOPIC_ASSET_MAP
        # In a real environment, we'd query the 'stakeholders' table for IDs.
        
        findings = []
        target_keys = TOPIC_ASSET_MAP.get(topic, TOPIC_ASSET_MAP["global"])
        
        # [v10.10] Sequential Chaining Logic: A -> B -> C
        # We pick 3 distinct assets and link them.
        
        chain = []
        for i, asset_id in enumerate(target_keys[:3]):
            target_name = asset_id.replace("_", " ").title()
            
            # Simple simulation of "impact" (attenuated per level)
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
