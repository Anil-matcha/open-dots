import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import httpx

from app.services.action_gateway import ActionGateway, ActionInvocation
from app.services.approval_broker import ApprovalBroker
from app.services.computer_actions import register_computer_actions
from app.services.computer_provider import FakeComputerProvider
from app.services.workspace_service import WorkspaceService

try:
    from app.main import app
    from app.services.auth_service import auth_service
    from app.services.storage_service import storage_service
except ModuleNotFoundError:
    app = None
    auth_service = None
    storage_service = None


class RecordingAudit:
    def __init__(self):
        self.events = []

    def add_audit_event(self, event: Dict[str, Any]):
        self.events.append(event)


class ImmediateApprovalBroker:
    def __init__(self, decision: str = "allow"):
        self.decision = decision
        self.opened = []

    def open(
        self,
        thread_id: str,
        bot_id: str,
        call: Any,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval = {
            "request_id": request_id,
            "thread_id": thread_id,
            "bot_id": bot_id,
            "tool": call.name,
            "summary": call.summary,
            "arguments": call.arguments_for_display,
            "status": "pending",
        }
        self.opened.append(approval)
        return approval

    async def wait(self, request_id: str) -> str:
        return self.decision


class FakeComputerProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_and_provider_operations_are_deterministic(self):
        provider = FakeComputerProvider()
        described = provider.describe("bot-test")
        self.assertEqual(described.state, "stopped")
        self.assertEqual(described.generation, 0)

        created = await provider.create("bot-test")
        self.assertEqual(created.computer_id, "computer-bot-test")
        self.assertEqual(created.generation, 1)

        started = await provider.start(created.computer_id)
        self.assertEqual(started.state, "running")
        self.assertEqual(started.health, "healthy")

        first_frame = await provider.screenshot(created.computer_id)
        second_frame = await provider.screenshot(created.computer_id)
        self.assertTrue(first_frame["available"])
        self.assertNotEqual(first_frame["frame_id"], second_frame["frame_id"])

        navigated = await provider.browser_navigate(
            created.computer_id,
            "https://example.test/docs",
        )
        self.assertEqual(navigated["url"], "https://example.test/docs")

        terminal = await provider.terminal_execute(created.computer_id, "echo safe")
        self.assertEqual(terminal["exit_code"], 0)
        self.assertIn("no process was started", terminal["stdout"])

        files = await provider.files_list(created.computer_id)
        self.assertEqual(files["path"], "/workspace")
        input_result = await provider.send_input(
            created.computer_id,
            {"type": "click", "x": 10, "y": 20},
        )
        self.assertTrue(input_result["accepted"])

        paused = await provider.pause(created.computer_id)
        self.assertEqual(paused.state, "paused")
        stopped = await provider.stop(created.computer_id)
        self.assertEqual(stopped.state, "stopped")
        self.assertEqual((await provider.screenshot(created.computer_id))["available"], False)

        reset = await provider.reset(created.computer_id)
        self.assertEqual(reset.state, "stopped")
        self.assertEqual(reset.generation, 2)
        cleaned = await provider.cleanup(created.computer_id)
        self.assertEqual(cleaned["state"], "cleaned")
        self.assertEqual(provider.describe("bot-test").generation, 0)

    async def test_operations_require_an_active_computer(self):
        provider = FakeComputerProvider()
        created = await provider.create("bot-test")
        with self.assertRaisesRegex(RuntimeError, "not active"):
            await provider.terminal_execute(created.computer_id, "echo safe")

        await provider.start(created.computer_id)
        with self.assertRaisesRegex(RuntimeError, "absolute HTTP"):
            await provider.browser_navigate(created.computer_id, "javascript:alert(1)")


class ComputerGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audit = RecordingAudit()
        self.approvals = ImmediateApprovalBroker()
        self.gateway = ActionGateway(
            workspace=WorkspaceService(Path(self.temp_dir.name)),
            approvals=self.approvals,
            audit=self.audit,
        )
        self.provider = FakeComputerProvider()
        register_computer_actions(self.gateway, self.provider)

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_lifecycle_and_approval_gated_operations_use_gateway(self):
        start_call = ActionInvocation(
            name="computer.start",
            arguments={"bot_id": "bot-test"},
            target={"bot_id": "bot-test"},
            preview="Start the bot computer",
        )
        start_request, approval = self.gateway.open("computer:bot-test", "bot-test", start_call)
        self.assertIsNone(approval)
        self.assertEqual((await self.gateway.execute(start_request)).status, "completed")

        terminal_call = ActionInvocation(
            name="computer.terminal_execute",
            arguments={"bot_id": "bot-test", "command": "echo safe"},
            target={"bot_id": "bot-test"},
            preview="Run a terminal command on the bot computer",
        )
        terminal_request, approval = self.gateway.open("computer:bot-test", "bot-test", terminal_call)
        self.assertIsNotNone(approval)
        self.assertEqual(await self.gateway.wait_for_decision(terminal_request), "allow")
        terminal_result = await self.gateway.execute(terminal_request)
        self.assertEqual(terminal_result.status, "completed")
        self.assertEqual(terminal_result.result["operation"], "terminal.exec")

        event_names = [event["event"] for event in self.audit.events]
        self.assertEqual(event_names.count("action.requested"), 2)
        self.assertIn("action.completed", event_names)


class ComputerRouterTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipIf(app is None, "FastAPI dependencies are not installed")
    async def test_cancelled_terminal_request_cannot_be_executed_again(self):
        bot_id = storage_service.get_bots()[0]["id"]
        provider = FakeComputerProvider()
        broker = ApprovalBroker()
        audit = RecordingAudit()
        gateway = ActionGateway(approvals=broker, audit=audit)
        register_computer_actions(gateway, provider)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def terminal_execute(computer_id, command):
            calls.append(command)
            started.set()
            await release.wait()
            return {"accepted": True}

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 43124))
        with (
            patch("app.routers.computers.action_gateway", gateway),
            patch("app.routers.computers.computer_provider", provider),
            patch("app.routers.approvals.approval_broker", broker),
            patch.object(provider, "terminal_execute", terminal_execute),
        ):
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                login = await client.post("/api/v1/auth/login", json={"token": auth_service.token})
                self.assertEqual(login.status_code, 200)
                action = await client.post(
                    f"/api/v1/computers/{bot_id}/actions",
                    json={"action": "terminal_execute", "arguments": {"command": "echo test"}},
                )
                self.assertEqual(action.status_code, 202)
                request_id = action.json()["request"]["request_id"]
                decision = await client.post(
                    "/api/v1/approvals/respond",
                    json={"request_id": request_id, "action": "allow"},
                )
                self.assertEqual(decision.status_code, 200)
                url = f"/api/v1/computers/{bot_id}/actions/{request_id}/execute"
                task = asyncio.create_task(client.post(url))
                try:
                    await asyncio.wait_for(started.wait(), timeout=5)
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                release.set()
                retry = await client.post(url)
                self.assertEqual(retry.status_code, 404)
                self.assertEqual(calls, ["echo test"])
                self.assertEqual(audit.events[-1]["event"], "action.failed")

    @unittest.skipIf(app is None, "FastAPI dependencies are not installed")
    async def test_authenticated_lifecycle_screen_and_approval_routes(self):
        bot_id = storage_service.get_bots()[0]["id"]
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 43124))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            session = await client.post("/api/v1/auth/login", json={"token": auth_service.token})
            self.assertEqual(session.status_code, 200)

            initial = await client.get(f"/api/v1/computers/{bot_id}")
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json()["status"]["provider"], "fake")

            started = await client.post(f"/api/v1/computers/{bot_id}/start")
            self.assertEqual(started.status_code, 200)
            self.assertEqual(started.json()["result"]["state"], "running")

            screen = await client.post(f"/api/v1/computers/{bot_id}/screenshot")
            self.assertEqual(screen.status_code, 200)
            self.assertTrue(screen.json()["result"]["available"])

            action = await client.post(
                f"/api/v1/computers/{bot_id}/actions",
                json={
                    "action": "terminal_execute",
                    "arguments": {"command": "echo safe", "bot_id": "bot-other"},
                },
            )
            self.assertEqual(action.status_code, 202)
            self.assertEqual(action.json()["request"]["bot_id"], bot_id)
            request_id = action.json()["request"]["request_id"]

            decision = await client.post(
                "/api/v1/approvals/respond",
                json={"request_id": request_id, "action": "allow"},
            )
            self.assertEqual(decision.status_code, 200)
            executed = await client.post(
                f"/api/v1/computers/{bot_id}/actions/{request_id}/execute"
            )
            self.assertEqual(executed.status_code, 200)
            self.assertEqual(executed.json()["result"]["operation"], "terminal.exec")

            paused = await client.post(f"/api/v1/computers/{bot_id}/pause")
            self.assertEqual(paused.json()["result"]["state"], "paused")


if __name__ == "__main__":
    unittest.main()
