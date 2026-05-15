"""
UN Comtrade API Client.

Supports fetching international trade data (Imports/Exports) by commodity 
and country using the UN Comtrade API v2.
"""

import logging
from typing import Dict, Any, Optional
from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class ComtradeClient(BaseAPIClient):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="UN Comtrade",
            base_url="https://comtradeapi.un.org",
            api_key_env="COMTRADE_API_KEY",
            api_key_required=True
        )
        if api_key:
            self.api_key = api_key

    def get_trade_data(
        self,
        reporter_code: str,
        partner_code: str,
        flow_code: str,
        commodity_code: str,
        year: int,
        frequency: str = "A",
        classification: str = "HS"
    ) -> Dict[str, Any]:
        """
        Fetch trade data for a specific reporter, partner, and commodity.
        """
        # Endpoint: /data/v1/get/{type}/{frequency}/{classification}
        path = f"data/v1/get/C/{frequency}/{classification}"
        
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key
        }
        
        params = {
            "reporterCode": reporter_code,
            "partnerCode": partner_code,
            "flowCode": flow_code,
            "cmdCode": commodity_code,
            "period": str(year),
            "format": "JSON"
        }
        
        try:
            return self.get_json(path, params=params, headers=headers)
        except Exception as e:
            logger.error(f"Comtrade API request failed: {e}")
            # Maintain compatibility with expected error return format in tests
            return {
                "error": True,
                "message": str(e),
                "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None,
                "response_text": getattr(e.response, 'text', str(e)) if hasattr(e, 'response') else str(e)
            }

    def get_metadata(self, type_code: str) -> Dict[str, Any]:
        """
        Fetch reference metadata (e.g., reporter codes, partner codes).
        """
        path = f"files/v1/get/reference/{type_code}"
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        
        try:
            return self.get_json(path, headers=headers)
        except Exception as e:
            logger.error(f"Failed to fetch Comtrade metadata for {type_code}: {e}")
            return {"error": str(e)}
