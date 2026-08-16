"""
FRED (Federal Reserve Economic Data) API Client.

Supports fetching economic timeseries data (Interest Rates, CPI, Oil, etc.)
from the St. Louis Fed API.
"""

import logging
from typing import Dict, Any, Optional
from data_sources.base_client import BaseAPIClient, redact_credentials

logger = logging.getLogger(__name__)

class FREDClient(BaseAPIClient):
    """
    Client for interacting with the FRED API.
    Requires a valid API key from https://fred.stlouisfed.org/docs/api/api_key.html
    """
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="FRED",
            base_url="https://api.stlouisfed.org/fred/",
            api_key_env="FRED_API_KEY",
            api_key_required=True
        )
        if api_key:
            self.api_key = api_key

    def get_series_observations(
        self, 
        series_id: str, 
        limit: int = 100, 
        sort_order: str = 'desc',
        **kwargs
    ) -> Dict[str, Any]:
        """
        Fetch observations for a specific FRED series.
        """
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "limit": limit,
            "sort_order": sort_order
        }
        params.update(kwargs)
        
        try:
            return self.get_json("series/observations", params=params)
        except Exception as e:
            # api_key travels as a query parameter, so the HTTPError message carries it.
            # Redact both the log line and the returned dict: the dict has no reader
            # today, but it is one data.get("error") away from external_data_fetch_logs.
            safe = redact_credentials(e)
            logger.error(f"FRED API request failed for series {series_id}: {safe}")
            return {"error": safe, "series_id": series_id}
