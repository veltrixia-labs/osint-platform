"""
Frankfurter API Client.

A lightweight client for fetching foreign exchange reference rates 
from the European Central Bank (ECB) via frankfurter.app.
"""

import logging
from typing import Dict, Any, List, Optional
from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class FrankfurterClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            source_name="Frankfurter",
            base_url="https://api.frankfurter.dev/v1",
            api_key_required=False
        )

    def get_latest(self, base: str = "USD", symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Fetch the latest exchange rates.
        """
        params = {"base": base}
        if symbols:
            params["symbols"] = ",".join(symbols)
            
        return self.get_json("latest", params=params)

    def get_timeseries(self, start_date: str, end_date: str, base: str = "USD", symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Fetch historical exchange rates for a time period.
        dates format: YYYY-MM-DD
        """
        path = f"{start_date}..{end_date}"
        params = {"base": base}
        if symbols:
            params["symbols"] = ",".join(symbols)
            
        return self.get_json(path, params=params)
