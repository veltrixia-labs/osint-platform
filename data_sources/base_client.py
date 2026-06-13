"""
Base API Client for external data sources.

Provides common functionality for authentication, HTTP requests, retries,
and error handling across all data source clients.
"""

import os
import time
import logging
import requests
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv(override=True)

logger = logging.getLogger(__name__)

class BaseAPIClient:
    """
    Unified base client for external economic and trade APIs.
    """
    def __init__(
        self,
        source_name: str,
        base_url: str,
        api_key_env: Optional[str] = None,
        api_key_required: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.5
    ):
        self.source_name = source_name
        self.base_url = base_url.rstrip('/')
        self.api_key_env = api_key_env
        self.api_key_required = api_key_required
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        
        self.api_key = self._load_api_key()
        self.session = requests.Session()

    def _load_api_key(self) -> Optional[str]:
        """Load API key from environment variables."""
        if not self.api_key_env:
            return None
            
        api_key = os.getenv(self.api_key_env)
        if not api_key and self.api_key_required:
            raise ValueError(f"CRITICAL: {self.api_key_env} not found in environment.")
        
        if not api_key:
            logger.warning(f"Optional API key {self.api_key_env} missing for {self.source_name}.")
            
        return api_key

    def _request(
        self,
        method: str,
        path_or_url: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None
    ) -> Union[Dict[str, Any], List[Any]]:
        """
        Execute an HTTP request with automatic retries and error handling.
        """
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}/{path_or_url.lstrip('/')}"
        
        request_headers = headers or {}
        
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=payload,
                    headers=request_headers,
                    timeout=self.timeout
                )
                
                # Handle Rate Limiting (HTTP 429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"Rate limit hit for {self.source_name}. Waiting {retry_after}s.")
                    time.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code is not None and 400 <= status_code < 500 and status_code != 429:
                    logger.warning(f"{self.source_name}: client error {status_code} — not retrying (series/endpoint invalid): {e}")
                    if hasattr(e, "response") and hasattr(e.response, "text"):
                        logger.error(f"Response Body: {e.response.text}")
                    raise
                if attempt < self.max_retries:
                    sleep_time = self.backoff_factor * (2 ** attempt)
                    logger.warning(f"Request failed for {self.source_name} (Attempt {attempt+1}/{self.max_retries+1}): {e}. Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                else:
                    logger.error(f"Final request failure for {self.source_name}: {e}")
                    if hasattr(e.response, 'text'):
                        logger.error(f"Response Body: {e.response.text}")
                    raise

        return {}

    def get_json(self, path_or_url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, Any]] = None) -> Union[Dict[str, Any], List[Any]]:
        """Perform a GET request and return JSON."""
        return self._request("GET", path_or_url, params=params, headers=headers)

    def post_json(self, path_or_url: str, payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, Any]] = None) -> Union[Dict[str, Any], List[Any]]:
        """Perform a POST request and return JSON."""
        return self._request("POST", path_or_url, payload=payload, headers=headers)
