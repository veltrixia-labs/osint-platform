import logging
from typing import Dict, Any, Optional
from data_sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

class BEAClient(BaseAPIClient):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            source_name="BEA",
            base_url="https://apps.bea.gov/api/data",
            api_key_env="BEA_API_KEY",
            api_key_required=True
        )
        if api_key:
            self.api_key = api_key

    def _make_request(self, method: str, **kwargs) -> Dict[str, Any]:
        params = {
            "UserID": self.api_key,
            "method": method,
            "ResultFormat": "JSON"
        }
        params.update(kwargs)
        # BEA uses base_url for all requests
        return self.get_json("", params=params)

    def get_datasets(self) -> Dict[str, Any]:
        """
        Retrieves a list of datasets available in the BEA API.
        """
        return self._make_request("GetDataSetList")

    def get_parameter_list(self, dataset_name: str) -> Dict[str, Any]:
        """
        Retrieves a list of parameters required for a specific dataset.
        """
        return self._make_request("GetParameterList", datasetname=dataset_name)

    def get_parameter_values(self, dataset_name: str, parameter_name: str) -> Dict[str, Any]:
        """
        Retrieves a list of valid values for a specific parameter in a dataset.
        """
        return self._make_request("GetParameterValues", datasetname=dataset_name, ParameterName=parameter_name)

    def get_data(self, dataset_name: str, **params) -> Dict[str, Any]:
        """
        Retrieves data for a specific dataset.
        """
        response_data = self._make_request("GetData", datasetname=dataset_name, **params)
        
        # Workaround for BEA API typo: "IndustrYDescription" -> "IndustryDescription"
        try:
            results = response_data.get("BEAAPI", {}).get("Results", [])
            data_list = []
            
            if isinstance(results, list) and len(results) > 0:
                data_list = results[0].get("Data", [])
            elif isinstance(results, dict):
                data_list = results.get("Data", [])
                
            for item in data_list:
                if "IndustrYDescription" in item and "IndustryDescription" not in item:
                    item["IndustryDescription"] = item["IndustrYDescription"]
        except Exception:
            pass # Ignore if structure is different
            
        return response_data
