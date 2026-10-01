import unittest
from unittest.mock import Mock, patch

from app.services.computer_provider import ComputerProviderError
from app.services.remote_computer_provider import RemoteComputerProvider


class StubRemoteComputerProvider(RemoteComputerProvider):
    def __init__(self):
        super().__init__(
            base_url="https://computer.example.test/api",
            api_key="secret-value",
            start_timeout=0.5,
            timeout=0.5,
        )
        self.calls = []

    async def _request(self, method, route, payload=None, *, timeout=None, ok_if_not_found=False):
        self.calls.append((method, route, payload))
        if method == "POST" and route == "/computers":
            return {
                "id": "remote-session-1",
                "state": "created",
                "width": 1440,
                "height": 900,
            }
        if route.endswith("/start"):
            return {"status": "ready", "health": "healthy"}
        if route.endswith("/stop"):
            return {"state": "stopped", "health": "unknown"}
        if route.endswith("/pause"):
            return {"state": "paused", "health": "healthy"}
        if route.endswith("/reset"):
            return {"state": "stopped", "health": "unknown"}
        if route.endswith("/health"):
            return {"status": "healthy", "width": 1440, "height": 900}
        if route.endswith("/navigate"):
            return {"url": payload["url"], "title": "Example"}
        if route.endswith("/terminal"):
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}
        if route.endswith("/files"):
            return {"path": payload["path"], "entries": []}
        if route.endswith("/screenshot"):
            return {
                "frame_id": "remote-frame-1",
                "format": "jpeg",
                "width": 1440,
                "height": 900,
                "data": "base64-jpeg",
            }
        if route.endswith("/input"):
            return {"accepted": True, "type": payload["event"]["type"]}
        if method == "DELETE":
            return {}
        raise AssertionError(f"Unhandled remote call: {method} {route}")


async def _awaitable(value):
    return value


class _FakeHttpResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class RemoteComputerProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_lifecycle_and_operations_use_the_provider_contract(self):
        provider = StubRemoteComputerProvider()
        described = provider.describe("bot-test")
        self.assertEqual(described.provider, "remote-api")
        self.assertEqual(described.generation, 0)

        created = await provider.create("bot-test")
        self.assertEqual(created.generation, 1)
        self.assertEqual(created.width, 1440)
        self.assertEqual(created.height, 900)

        started = await provider.start(created.computer_id)
        self.assertEqual(started.state, "running")
        self.assertEqual(started.health, "healthy")

        navigated = await provider.browser_navigate(
            created.computer_id,
            "https://example.test/docs",
        )
        self.assertEqual(navigated["title"], "Example")

        terminal = await provider.terminal_execute(created.computer_id, "printf safe")
        self.assertEqual(terminal["stdout"], "ok")

        files = await provider.files_list(created.computer_id, "/workspace")
        self.assertEqual(files["entries"], [])

        input_result = await provider.send_input(
            created.computer_id,
            {"type": "click", "x": 4, "y": 5},
        )
        self.assertTrue(input_result["accepted"])

        screen = await provider.screenshot(created.computer_id)
        self.assertTrue(screen["available"])
        self.assertEqual(screen["frame_id"], "remote-frame-1")
        self.assertEqual(provider.describe("bot-test").frame_id, "remote-frame-1")

        paused = await provider.pause(created.computer_id)
        self.assertEqual(paused.state, "paused")
        stopped = await provider.stop(created.computer_id)
        self.assertEqual(stopped.state, "stopped")
        self.assertFalse((await provider.screenshot(created.computer_id))["available"])

        reset = await provider.reset(created.computer_id)
        self.assertEqual(reset.state, "stopped")
        self.assertEqual(reset.generation, 2)
        cleaned = await provider.cleanup(created.computer_id)
        self.assertEqual(cleaned["state"], "cleaned")

        self.assertEqual(provider.calls[0][0:2], ("POST", "/computers"))
        self.assertIn("/computers/remote-session-1/start", [call[1] for call in provider.calls])

    async def test_cleanup_of_never_created_computer_is_a_noop(self):
        provider = StubRemoteComputerProvider()
        status = provider.describe("bot-test")
        cleaned = await provider.cleanup(status.computer_id)
        self.assertEqual(cleaned["state"], "cleaned")
        self.assertEqual(cleaned["computer_id"], status.computer_id)
        self.assertEqual(provider.calls, [])
        # Second cleanup stays idempotent.
        cleaned_again = await provider.cleanup(status.computer_id)
        self.assertEqual(cleaned_again["state"], "cleaned")

    async def test_remote_provider_requires_an_endpoint_and_key(self):
        provider = RemoteComputerProvider(base_url="", api_key="")
        status = provider.get_or_create("bot-test")
        with self.assertRaisesRegex(ComputerProviderError, "COMPUTER_REMOTE_API_KEY"):            await provider.start(status.computer_id)

    async def test_delete_tolerates_remote_404_but_not_other_errors(self):
        provider = RemoteComputerProvider(
            base_url="https://computer.example.test/api",
            api_key="secret",
            start_timeout=0.5,
            timeout=0.5,
        )

        def client_for(response):
            client = Mock()
            client.request = Mock(side_effect=lambda *a, **k: _awaitable(response))
            context = Mock()
            context.__aenter__ = Mock(side_effect=lambda *a, **k: _awaitable(client))
            context.__aexit__ = Mock(side_effect=lambda *a, **k: _awaitable(False))
            factory = Mock(return_value=context)
            return factory

        gone = _FakeHttpResponse(404, {"error": "no such computer"})
        with patch(
            "app.services.remote_computer_provider.httpx.AsyncClient",
            client_for(gone),
        ):
            # Already deleted remotely: the desired end state, not a failure.
            self.assertEqual(
                await provider._request(
                    "DELETE", "/computers/remote-gone", ok_if_not_found=True
                ),
                {},
            )
            # Without the flag a 404 is still surfaced.
            with self.assertRaises(ComputerProviderError):
                await provider._request("DELETE", "/computers/remote-gone")

        broken = _FakeHttpResponse(500, {"error": "boom"})
        with patch(
            "app.services.remote_computer_provider.httpx.AsyncClient",
            client_for(broken),
        ):
            # The flag only forgives 404, never real failures.
            with self.assertRaises(ComputerProviderError):
                await provider._request(
                    "DELETE", "/computers/remote-x", ok_if_not_found=True
                )

    async def test_cleanup_still_surfaces_non_404_remote_failures(self):
        class FailingDeleteProvider(StubRemoteComputerProvider):
            async def _request(
                self, method, route, payload=None, *, timeout=None,
                ok_if_not_found=False,
            ):
                if method == "DELETE":
                    raise ComputerProviderError("remote exploded")
                return await super()._request(
                    method, route, payload, timeout=timeout,
                    ok_if_not_found=ok_if_not_found,
                )

        provider = FailingDeleteProvider()
        created = provider.get_or_create("bot-test")
        await provider.start(created.computer_id)
        with self.assertRaisesRegex(ComputerProviderError, "remote exploded"):
            await provider.cleanup(created.computer_id)


if __name__ == "__main__":
    unittest.main()
