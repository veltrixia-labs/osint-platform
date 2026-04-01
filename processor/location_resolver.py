import json
import os
import re
from typing import Optional, Tuple, Dict

class LocationResolver:
    def __init__(self, static_map_path: str = "processor/static_locations.json"):
        self.static_map_path = static_map_path
        self.locations = self._load_static_map()

    def _load_static_map(self) -> Dict:
        if os.path.exists(self.static_map_path):
            with open(self.static_map_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def resolve_heuristically(self, text: str) -> Optional[Tuple[float, float]]:
        """
        Scan text for known locations from the static map.
        Returns first match (lat, lng) or None.
        """
        for name, coords in self.locations.items():
            # Use word boundaries to avoid partial matches (e.g., "Iran" in "Uraniun")
            if re.search(r'\b' + re.escape(name) + r'\b', text, re.IGNORECASE):
                return (coords["lat"], coords["lng"])
        return None

    def resolve_full(self, text: str, llm_client=None) -> Optional[Tuple[float, float]]:
        """
        Hybrid resolution:
        1. Heuristic check (Zero Cost)
        2. LLM fallback (Only if llm_client is provided/authorized)
        """
        heuristic_hit = self.resolve_heuristically(text)
        if heuristic_hit:
            return heuristic_hit
        
        if llm_client:
            # Placeholder for targeted LLM extraction logic
            # This would only be called for high-fidelity signals
            return self._llm_extract(text, llm_client)
            
        return None

    def _llm_extract(self, text: str, llm_client) -> Optional[Tuple[float, float]]:
        # In a real scenario, this calls the LLM with a specific prompt:
        # "Extract the primary geographic coordinates (lat, lng) for the main event in this text. 
        # Return only JSON: {'lat': ..., 'lng': ...}"
        return None # To be implemented when LLM integration is wired
