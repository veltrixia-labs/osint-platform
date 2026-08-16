"""
Census Bureau API Client.

Supports fetching data from various Census datasets including 
Economic Indicators, County Business Patterns, and International Trade.
"""

import logging
from typing import List, Dict, Any, Optional
from data_sources.base_client import BaseAPIClient, redact_credentials

logger = logging.getLogger(__name__)

class CensusClient(BaseAPIClient):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="Census",
            base_url="https://api.census.gov/data",
            api_key_env="CENSUS_API_KEY",
            api_key_required=False # Some public data doesn't strictly need it but it's recommended
        )
        if api_key:
            self.api_key = api_key

    def get(self, dataset_path: str, params: Dict[str, Any]) -> List[Any]:
        """
        Generic GET request for Census data.
        """
        path = dataset_path.strip('/')
        
        # Ensure we include the API key if available
        if self.api_key:
            params["key"] = self.api_key

        try:
            return self.get_json(path, params=params)
        except Exception as e:
            # The key travels as the "key" query parameter, so the HTTPError message
            # carries it. Redact the returned row too: sync_census_cbp persists this
            # value verbatim into external_industry_stats.raw_json.
            safe = redact_credentials(e)
            logger.error(f"Census API request failed for {dataset_path}: {safe}")
            return [["error"], [safe]]

    def get_variables(self, dataset_path: str) -> Dict[str, Any]:
        """
        Fetch the list of variables available for a dataset.
        """
        path = f"{dataset_path.strip('/')}/variables.json"
        
        try:
            return self.get_json(path)
        except Exception as e:
            safe = redact_credentials(e)
            logger.error(f"Failed to fetch variables for {dataset_path}: {safe}")
            return {"error": safe}

    def format_as_dicts(self, data: List[List[Any]]) -> List[Dict[str, Any]]:
        """
        Helper to convert Census list-of-lists response to a list of dictionaries.
        """
        if not isinstance(data, list) or len(data) < 2:
            return []
            
        headers = data[0]
        rows = data[1:]
        
        return [dict(zip(headers, row)) for row in rows]
