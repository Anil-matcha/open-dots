"""Small Serply adapter used by governed search actions."""

from typing import Any, Dict

import httpx

from app.config import settings
from app.services.storage_service import StorageService, storage_service
from app.services.youcom_service import MAX_QUERY_CHARS, SearchServiceError


SERPLY_SEARCH_URL = "https://api.serply.io/v1/search"
SERPLY_USER_AGENT = "open-dots"


class SerplyService:
    def __init__(self, storage: StorageService = storage_service):
        self.storage = storage

    def get_api_key(self) -> str:
        config = self.storage.get_settings()
        return str(config.get("serply_api_key") or settings.SERPLY_API_KEY or "")

    async def fetch(self, query: str, count: int) -> Dict[str, Any]:
        key = self.get_api_key()
        if not key:
            raise SearchServiceError("Set SERPLY_API_KEY to search with Serply.")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                SERPLY_SEARCH_URL,
                params={"q": query, "num": count},
                headers={
                    "accept": "application/json",
                    "user-agent": SERPLY_USER_AGENT,
                    "x-api-key": key,
                },
            )
            if response.status_code in (401, 403):
                raise SearchServiceError("Serply rejected the configured API key.")
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def search_web(
        self,
        query: str,
        count: int = 5,
    ) -> Dict[str, Any]:
        query = (query or "").strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            raise SearchServiceError(
                f"A search query must be between 1 and {MAX_QUERY_CHARS} characters."
            )
        if not isinstance(count, int) or not 1 <= count <= 10:
            raise SearchServiceError("The search result count must be between 1 and 10.")

        payload = await self.fetch(query, count)
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raw_results = []

        results = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "")
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                {
                    "title": item.get("title"),
                    "url": url,
                    "snippet": str(item.get("description") or "").strip()[:280],
                    "highlights": [],
                }
            )
            if len(results) == count:
                break

        return {
            "provider": "serply",
            "operation": "web_search",
            "query": query,
            "count": len(results),
            "results": results,
        }


serply_service = SerplyService()
