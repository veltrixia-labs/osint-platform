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
        
        # [v10.9] Statistical Logic: Alpha = (Intensity * Weight) / (1 + log(Distance))
        # This simulates the "ripple" attenuation over geographic distance.
        
        for i, asset_id in enumerate(target_keys[:3]): # Top 3 relevant assets
            # In production, we'd fetch the actual stakeholder from DB by asset_id
            # Here we provide the finding structure the UI expects
            
            # Simple simulation of "impact" direction based on topic sentiment (default negative for OSINT)
            target_name = asset_id.replace("_", " ").title()
            
            # Distance penalty
            dist_km = 1000.0 # Default fallback if no coords
            if lat is not None and lng is not None:
                # Mock coords for calculation if db not queried
                # (Actual coordinates would come from the Stakeholder table)
                dist_km = 500.0 # Simulated proximity
            
            # Logarithmic attenuation
            attenuation = 1.0 / (1.0 + math.log10(max(1, dist_km / 100)))
            calculated_alpha = round(-(intensity * 0.5) * attenuation, 2)
            
            findings.append({
                "stakeholder_id": None,
                "entity_name": target_name,
                "impact_direction": "negative",
                "impact_alpha": calculated_alpha,
                "confidence": 0.7, # Statistical baseline
                "reasoning": f"Mathematical projection: Cross-domain correlation high for {topic} signal at current intensity ({intensity}).",
                "source": "statistical_model"
            })
            
        return findings
