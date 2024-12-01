# n8n/workflow_manager.py
import json
from typing import Optional, Tuple
import logging

from n8n.n8n_provider import N8nProvider, N8nResponse


class WorkflowConfig:
    SATISFACTION_ANALYSIS = {
        "name": "Satisfaction Analysis",
        "nodes": [
            {
                "id": "webhook",
                "parameters": {
                    "path": "satisfaction-analysis",
                    "options": {},
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                    "authentication": "none"
                },
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [250, 300]
            },
            {
                "id": "analyze",
                "parameters": {
                    "url": "={{ $env.API_HOST_URL }}/api/v1/analyze-satisfaction",
                    "method": "POST",
                    "authentication": "none",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "Content-Type",
                                "value": "application/json"
                            }
                        ]
                    },
                    "sendBody": True,
                    "bodyParameters": {
                        "parameters": [
                            {
                                "name": "data",
                                "value": "={{ $json }}"
                            }
                        ]
                    }
                },
                "name": "Analyze Satisfaction",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 3,
                "position": [450, 300]
            },
            {
                "id": "slack",
                "parameters": {
                    "url": "={{ $env.API_HOST_URL }}/api/v1/send-slack-message",
                    "method": "POST",
                    "authentication": "none",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "Content-Type",
                                "value": "application/json"
                            }
                        ]
                    },
                    "sendBody": True,
                    "bodyParameters": {
                        "parameters": [
                            {
                                "name": "channel_id",
                                "value": "={{ $json.body.message.channel_id }}"
                            },
                            {
                                "name": "text",
                                "value": "={{ $json.body.satisfaction_result }}"
                            },
                            {
                                "name": "thread_ts",
                                "value": "={{ $json.body.message.thread_ts }}"
                            }
                        ]
                    }
                },
                "name": "Send to Slack",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 3,
                "position": [650, 300]
            }
        ],
        "connections": {
            "Webhook": {
                "main": [
                    [
                        {
                            "node": "Analyze Satisfaction",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Analyze Satisfaction": {
                "main": [
                    [
                        {
                            "node": "Send to Slack",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            }
        },
        "settings": {
            "executionOrder": "v1"
        }
    }

class N8nWorkflowManager:
    def __init__(self, n8n_provider: N8nProvider):
        self.provider = n8n_provider
        self._workflow_cache = {}  # {workflow_name: {"id": "", "webhook_id": ""}}
        self.logger = logging.getLogger(__name__)

    async def _find_workflow(self, name: str) -> Optional[dict]:
        """Find workflow by name"""
        resp = await self.provider.get_workflows()
        if resp.success and resp.data:
            for workflow in resp.data.get('data', []):
                if workflow.get('name') == name:
                    return workflow
        return None

    async def _ensure_workflow(self, config: dict) -> str:
        """Get or create workflow and return workflow_id"""
        workflow_name = config["name"]

        if workflow_name not in self._workflow_cache:
            existing = await self._find_workflow(workflow_name)

            if not existing:
                self.logger.info(f"Creating new workflow: {workflow_name}")
                resp = await self.provider.create_workflow(config)
                if not resp.success:
                    raise Exception(f"Failed to create workflow: {resp.error}")
                workflow_id = resp.data["id"]
                await self.provider.activate_workflow(workflow_id)
            else:
                workflow_id = existing["id"]

            self._workflow_cache[workflow_name] = workflow_id

        return self._workflow_cache[workflow_name]

    def _get_webhook_path(self, config: dict) -> str:
        """Extract webhook path from webhook node configuration"""
        for node in config["nodes"]:
            if node["type"] == "n8n-nodes-base.webhook":
                return node["parameters"]["path"]
        raise ValueError("No webhook node found in workflow config")

    async def trigger_workflow(self, workflow_type: str, payload: dict) -> N8nResponse:
        """High-level workflow trigger by type"""
        try:
            self.logger.debug(f"Triggering workflow type: {workflow_type}")
            self.logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

            if workflow_type == "satisfaction":
                config = WorkflowConfig.SATISFACTION_ANALYSIS
            else:
                raise ValueError(f"Unknown workflow type: {workflow_type}")

            workflow_id = await self._ensure_workflow(config)
            webhook_path = self._get_webhook_path(config)

            self.logger.debug(f"Got workflow ID: {workflow_id}, webhook path: {webhook_path}")

            result = await self.provider.trigger_workflow_webhook(
                webhook_path,
                workflow_id,
                payload
            )
            self.logger.debug(f"Trigger result: {json.dumps(result.dict(), indent=2)}")
            return result
        except Exception as e:
            self.logger.error(f"Failed to trigger workflow: {str(e)}")
            self.logger.error(f"Full error: {repr(e)}")
            return N8nResponse(success=False, error=str(e))


    async def setup_workflows(self, recreate: bool = False) -> None:
        """Initialize all workflows"""
        try:
            if recreate:
                self.logger.info("Recreating all workflows...")
                resp = await self.provider.get_workflows()
                if resp.success and resp.data:
                    for workflow in resp.data.get('data', []):
                        if workflow_id := workflow.get('id'):
                            await self.provider.delete_workflow(workflow_id)
                self._workflow_cache.clear()

            # Initialize satisfaction workflow
            await self._ensure_workflow(WorkflowConfig.SATISFACTION_ANALYSIS)

        except Exception as e:
            self.logger.error(f"Failed to setup workflows: {str(e)}")
            raise