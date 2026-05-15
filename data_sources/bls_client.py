"""
BLS (Bureau of Labor Statistics) Public Data API Client.

Supports fetching timeseries data (PPI, CPI, etc.) using the BLS Public Data API v2.
"""

import logging
from typing import List, Dict, Any, Optional
from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class BLSClient(BaseAPIClient):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="BLS",
            base_url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
            api_key_env="BLS_API_KEY",
            api_key_required=False # Anonymous access is possible but limited
        )
        if api_key:
            self.api_key = api_key

    def get_timeseries(self, series_ids: List[str], start_year: int, end_year: int) -> Dict[str, Any]:
        """
        Fetch data for multiple series IDs.
        """
        if not series_ids:
            return {"status": "REQUEST_NOT_PROCESSED", "message": ["No series IDs provided."]}

        payload = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        
        if self.api_key:
            payload["registrationkey"] = self.api_key

        headers = {'Content-type': 'application/json'}
        
        try:
            # Use post_json from BaseAPIClient
            # Note: BLS base_url includes the trailing slash
            return self.post_json("", payload=payload, headers=headers)
        except Exception as e:
            logger.error(f"BLS API Request failed: {e}")
            return {
                "status": "REQUEST_FAILED",
                "message": [str(e)]
            }

    def parse_series_data(self, response: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Helper to extract data points from the raw response.
        """
        results = {}
        if response.get("status") != "REQUEST_SUCCEEDED":
            return results
            
        for series in response.get("Results", {}).get("series", []):
            series_id = series.get("seriesID")
            data_points = series.get("data", [])
            results[series_id] = data_points
            
        return results
