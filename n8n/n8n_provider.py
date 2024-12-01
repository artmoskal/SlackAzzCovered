# n8n/provider.py
import json
from typing import Any, Optional
import requests
import logging
from pydantic import BaseModel

class N8nResponse(BaseModel):
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None

class N8nProvider:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'X-N8N-API-KEY': api_key,
            'Content-Type': 'application/json'
        }
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

    async def trigger_workflow_webhook(self, webhook_path: str, workflow_id: str, payload: dict) -> N8nResponse:
        """Low-level webhook trigger using workflow ID"""
        try:
            url = f"{self.base_url}/webhook/{workflow_id}/webhook/{webhook_path}"
            self.logger.debug(f"Triggering webhook at URL: {url}")
            response = requests.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return N8nResponse(success=True, data=response.json())
        except Exception as e:
            self.logger.error(f"n8n webhook trigger error: {str(e)}")
            return N8nResponse(success=False, error=str(e))

    async def create_workflow(self, workflow_data: dict[str, Any]) -> N8nResponse:
        """Create a new workflow"""
        try:
            url = f"{self.base_url}/api/v1/workflows"
            self.logger.debug(f"Creating workflow at URL: {url}")
            self.logger.debug(f"Request headers: {json.dumps(self.headers, indent=2)}")
            self.logger.debug(f"Request payload: {json.dumps(workflow_data, indent=2)}")

            response = requests.post(url, json=workflow_data, headers=self.headers)
            self.logger.debug(f"Response status: {response.status_code}")
            self.logger.debug(f"Response body: {response.text}")

            response.raise_for_status()
            return N8nResponse(success=True, data=response.json())
        except Exception as e:
            self.logger.error(f"Failed to create workflow: {str(e)}")
            self.logger.error(f"Full error: {repr(e)}")
            return N8nResponse(success=False, error=str(e))

    async def get_workflows(self) -> N8nResponse:
        """Get all workflows"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/workflows",
                headers=self.headers
            )
            response.raise_for_status()
            return N8nResponse(success=True, data=response.json())
        except Exception as e:
            self.logger.error(f"Failed to get workflows: {str(e)}")
            return N8nResponse(success=False, error=str(e))

    async def delete_workflow(self, workflow_id: str) -> N8nResponse:
        """Delete a workflow"""
        try:
            response = requests.delete(
                f"{self.base_url}/api/v1/workflows/{workflow_id}",
                headers=self.headers
            )
            response.raise_for_status()
            return N8nResponse(success=True)
        except Exception as e:
            self.logger.error(f"Failed to delete workflow: {str(e)}")
            return N8nResponse(success=False, error=str(e))

    async def activate_workflow(self, workflow_id: str) -> N8nResponse:
        """Activate a workflow"""
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/workflows/{workflow_id}/activate",
                headers=self.headers
            )
            response.raise_for_status()
            return N8nResponse(success=True)
        except Exception as e:
            self.logger.error(f"Failed to activate workflow: {str(e)}")
            return N8nResponse(success=False, error=str(e))