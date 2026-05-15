"""
Alpha Vantage API Client.

Supports fetching market data including stock/ETF prices, forex rates, 
cryptocurrency data, and economic indicators.
"""

import logging
from typing import Dict, Any, Optional
from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class AlphaVantageClient(BaseAPIClient):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="Alpha Vantage",
            base_url="https://www.alphavantage.co",
            api_key_env="ALPHA_VANTAGE_API_KEY",
            api_key_required=True
        )
        if api_key:
            self.api_key = api_key

    def _query(self, function: str, **params) -> Dict[str, Any]:
        """Generic query method for Alpha Vantage."""
        query_params = {
            "function": function,
            "apikey": self.api_key
        }
        query_params.update(params)
        return self.get_json("query", params=query_params)

    def get_daily_equity(self, symbol: str, outputsize: str = "compact") -> Dict[str, Any]:
        """
        Fetch daily time series for a given equity (Stock or ETF).
        outputsize: 'compact' (last 100 points) or 'full' (up to 20 years).
        """
        return self._query("TIME_SERIES_DAILY", symbol=symbol, outputsize=outputsize)

    def get_daily_crypto(self, symbol: str, market: str = "USD") -> Dict[str, Any]:
        """
        Fetch daily time series for a given cryptocurrency.
        """
        return self._query("DIGITAL_CURRENCY_DAILY", symbol=symbol, market=market)

    def get_fx_daily(self, from_symbol: str, to_symbol: str, outputsize: str = "compact") -> Dict[str, Any]:
        """
        Fetch daily time series for a given forex pair.
        """
        return self._query("FX_DAILY", from_symbol=from_symbol, to_symbol=to_symbol, outputsize=outputsize)

    def get_exchange_rate(self, from_currency: str, to_currency: str) -> Dict[str, Any]:
        """
        Fetch real-time exchange rate for any pair (FX or Crypto).
        """
        return self._query("CURRENCY_EXCHANGE_RATE", from_currency=from_currency, to_currency=to_currency)
