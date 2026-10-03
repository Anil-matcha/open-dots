"""Cohesivity backend adapter for tenant and resource management via MCP."""

import json
from typing import Any, Dict

import httpx

from app.config import settings
from app.services.storage_service import StorageService, storage_service


COHESIVITY_MCP_URL = "https://cohesivity.ai/mcp"

VALID_RESOURCES = frozenset({
    "openweather-api",
    "google-geocoding-api",
    "openai-api",
    "ai-gateway",
    "deepgram-api",
    "exa-api",
    "steel-browser",
    "inbox",
    "postgres",
    "redis",
    "object-storage",
    "vector-database",
    "railway-hosting",
    "cloudflare-workers",
    "social-login",
    "realtime",
})


class BackendServiceError(ValueError):
    """Raised when a backend action cannot be validated or completed."""


def parse_mcp_response(text: str) -> Dict[str, Any]:
    """Return the decoded tool output from a Cohesivity MCP response.

    The endpoint answers with server-sent events and may emit progress
    notifications before the result, so the last ``data:`` line carrying
    a ``result`` wins.
    """
    result: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        if raw_line.startswith("data: "):
            line = raw_line[6:]
        elif raw_line.lstrip().startswith("{"):
            line = raw_line
        else:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("error"):
            error = message["error"]
            raise BackendServiceError(error.get("message", "The backend provider returned an error."))
        if "result" in message:
            result = message["result"]

    if not result:
        raise BackendServiceError("The backend provider returned an empty response.")

    content = next(
        (
            item.get("text")
            for item in (result.get("content") or [])
            if item.get("type") == "text"
        ),
        None,
    )
    if result.get("isError"):
        raise BackendServiceError(content or "The backend provider returned an error.")

    if not content:
        return result
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return {"text": content}
    return decoded if isinstance(decoded, dict) else {"data": decoded}


class CohesivityService:
    def __init__(self, storage: StorageService = storage_service):
        self.storage = storage

    def _get_credentials(self) -> Dict[str, str]:
        """Return tenant_id and management key from settings or env."""
        config = self.storage.get_settings()
        tenant_id = str(
            config.get("cohesivity_tenant_id")
            or settings.COHESIVITY_TENANT_ID
            or ""
        )
        management_key = str(
            config.get("cohesivity_management_key")
            or settings.COHESIVITY_MANAGEMENT_KEY
            or ""
        )
        return {"tenant_id": tenant_id, "management_key": management_key}

    def _get_endpoint(self) -> tuple[str, Dict[str, str]]:
        """Return the MCP endpoint URL and headers."""
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        return COHESIVITY_MCP_URL, headers

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Call a Cohesivity MCP tool via JSON-RPC."""
        url, headers = self._get_endpoint()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            response.raise_for_status()
            return parse_mcp_response(response.text)

    async def create_tenant(self) -> Dict[str, Any]:
        """Create a new Cohesivity tenant and return credentials."""
        return await self.call_tool("create_tenant", {"confirmed": True})

    async def get_status(self) -> Dict[str, Any]:
        """Check the status of the configured tenant."""
        creds = self._get_credentials()
        if not creds["tenant_id"] or not creds["management_key"]:
            raise BackendServiceError(
                "Set cohesivity_tenant_id and cohesivity_management_key in settings "
                "or COHESIVITY_TENANT_ID and COHESIVITY_MANAGEMENT_KEY environment variables."
            )
        return await self.call_tool(
            "tenant_status",
            {
                "tenant_id": creds["tenant_id"],
                "coh_management_key": creds["management_key"],
            },
        )

    async def provision_resource(self, resource: str) -> Dict[str, Any]:
        """Provision a resource for the configured tenant."""
        resource = (resource or "").strip().lower()
        if resource not in VALID_RESOURCES:
            raise BackendServiceError(
                f"Unknown resource: {resource}. "
                f"Valid resources: {', '.join(sorted(VALID_RESOURCES))}"
            )
        creds = self._get_credentials()
        if not creds["tenant_id"] or not creds["management_key"]:
            raise BackendServiceError(
                "Set cohesivity_tenant_id and cohesivity_management_key in settings "
                "or COHESIVITY_TENANT_ID and COHESIVITY_MANAGEMENT_KEY environment variables."
            )
        return await self.call_tool(
            "provision_resource",
            {
                "tenant_id": creds["tenant_id"],
                "coh_management_key": creds["management_key"],
                "resource": resource,
                "confirmed": True,
            },
        )


cohesivity_service = CohesivityService()
