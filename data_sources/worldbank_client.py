"""
World Bank Open Data API Client.

Supports fetching international economic indicators such as GDP, Inflation, 
Trade, and Population for multiple countries.
"""

import logging
from typing import List, Dict, Any, Optional
from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class WorldBankClient(BaseAPIClient):
    def __init__(self):
        super().__init__(
            source_name="World Bank",
            base_url="https://api.worldbank.org/v2",
            api_key_env=None,
            api_key_required=False
        )

    def get_indicator(
        self,
        countries: List[str],
        indicator: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch data for a specific indicator across multiple countries.
        """
        country_str = ";".join(countries)
        path = f"country/{country_str}/indicator/{indicator}"
        
        params = {
            "format": "json",
            "per_page": 1000
        }
        
        if start_year and end_year:
            params["date"] = f"{start_year}:{end_year}"
        elif start_year:
            params["date"] = f"{start_year}"

        try:
            raw_data = self.get_json(path, params=params)
            
            # World Bank JSON response is [metadata, data_list]
            if isinstance(raw_data, list) and len(raw_data) == 2:
                data_list = raw_data[1]
                
                if data_list is None:
                    logger.warning(f"No data returned for indicator {indicator} and countries {countries}")
                    return []
                    
                return data_list
            else:
                logger.error(f"Unexpected response format from World Bank API for {indicator}")
                return []

        except Exception as e:
            logger.error(f"World Bank API request failed for {indicator}: {e}")
            return []

    def format_data_point(self, dp: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cleans up a single World Bank data point.
        """
        return {
            "country_id": dp.get("country", {}).get("id"),
            "country_name": dp.get("country", {}).get("value"),
            "indicator_id": dp.get("indicator", {}).get("id"),
            "indicator_name": dp.get("indicator", {}).get("value"),
            "date": dp.get("date"),
            "value": dp.get("value"),
            "decimal": dp.get("decimal")
        }
