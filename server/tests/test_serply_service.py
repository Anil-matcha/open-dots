import unittest
from dataclasses import replace
from unittest import mock

from app.services import search_actions
from app.services.search_actions import execute_web_search, parse_search_command
from app.services.serply_service import SERPLY_SEARCH_URL, SerplyService
from app.services.youcom_service import SearchServiceError


class EmptyStorage:
    def get_settings(self):
        return {}


class KeyStorage:
    def get_settings(self):
        return {"serply_api_key": "stored-key"}


FAKE_SERPLY_OUTPUT = {
    "results": [
        {
            "title": "FastAPI Releases",
            "link": "https://example.com/fastapi",
            "description": "Release notes and current version details.",
        },
        {
            "title": "Cached token",
            "link": "CAESBQoDCAE",
            "description": "Not a URL and should be dropped.",
        },
        {
            "title": "Pydantic Changelog",
            "link": "https://example.com/pydantic",
            "description": "Historic changelog entries.",
        },
        {
            "title": "Third",
            "link": "https://example.com/third",
            "description": "Trimmed by count.",
        },
    ]
}


class FakeSerplyService(SerplyService):
    async def fetch(self, query, count):
        self.called = (query, count)
        return FAKE_SERPLY_OUTPUT


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return self.response


class SerplyServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_stored_key_wins_over_env(self):
        with mock.patch("app.services.serply_service.settings.SERPLY_API_KEY", "env-key"):
            self.assertEqual(SerplyService(KeyStorage()).get_api_key(), "stored-key")
            self.assertEqual(SerplyService(EmptyStorage()).get_api_key(), "env-key")

    async def test_search_maps_results_and_drops_non_web_links(self):
        provider = FakeSerplyService(EmptyStorage())
        result = await provider.search_web("latest fastapi release notes", count=2)

        self.assertEqual(provider.called, ("latest fastapi release notes", 2))
        self.assertEqual(result["provider"], "serply")
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [item["url"] for item in result["results"]],
            ["https://example.com/fastapi", "https://example.com/pydantic"],
        )
        self.assertEqual(result["results"][0]["snippet"], "Release notes and current version details.")

    async def test_fetch_sends_key_in_header_not_query(self):
        client = RecordingClient(FakeResponse(200, FAKE_SERPLY_OUTPUT))
        with mock.patch("app.services.serply_service.httpx.AsyncClient", return_value=client):
            await SerplyService(KeyStorage()).fetch("fastapi", 5)

        url, params, headers = client.calls[0]
        self.assertEqual(url, SERPLY_SEARCH_URL)
        self.assertEqual(params, {"q": "fastapi", "num": 5})
        self.assertEqual(headers["x-api-key"], "stored-key")
        self.assertEqual(headers["user-agent"], "open-dots")

    async def test_rejected_key_raises_search_error(self):
        client = RecordingClient(FakeResponse(401, {"detail": "Invalid API key"}))
        with (
            mock.patch("app.services.serply_service.httpx.AsyncClient", return_value=client),
            self.assertRaises(SearchServiceError),
        ):
            await SerplyService(KeyStorage()).fetch("fastapi", 5)

    async def test_missing_key_raises_without_request(self):
        with (
            mock.patch("app.services.serply_service.settings.SERPLY_API_KEY", ""),
            mock.patch("app.services.serply_service.httpx.AsyncClient") as client,
        ):
            with self.assertRaises(SearchServiceError):
                await SerplyService(EmptyStorage()).fetch("fastapi", 5)
            client.assert_not_called()

    async def test_invalid_count_is_rejected(self):
        with self.assertRaises(SearchServiceError):
            await FakeSerplyService(EmptyStorage()).search_web("fastapi", count=11)


class SearchRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_targets_youcom_without_serply_key(self):
        with mock.patch.object(search_actions.serply_service, "get_api_key", return_value=""):
            call = parse_search_command("/search latest fastapi release notes")
        self.assertEqual(call.target, {"provider": "youcom"})

    def test_parser_targets_serply_with_key(self):
        with mock.patch.object(search_actions.serply_service, "get_api_key", return_value="key"):
            call = parse_search_command("/search latest fastapi release notes")
        self.assertEqual(call.target, {"provider": "serply"})

    async def test_execute_dispatches_on_target_provider(self):
        call = parse_search_command("/search fastapi")
        with mock.patch.object(
            search_actions.serply_service, "search_web", mock.AsyncMock(return_value={"provider": "serply"})
        ) as serply, mock.patch.object(
            search_actions.youcom_service, "search_web", mock.AsyncMock(return_value={"provider": "youcom"})
        ) as youcom:
            serply_call = replace(call, target={"provider": "serply"})
            youcom_call = replace(call, target={"provider": "youcom"})
            self.assertEqual((await execute_web_search(serply_call))["provider"], "serply")
            self.assertEqual((await execute_web_search(youcom_call))["provider"], "youcom")
        serply.assert_awaited_once_with(query="fastapi", count=5)
        youcom.assert_awaited_once_with(query="fastapi", count=5)


if __name__ == "__main__":
    unittest.main()
