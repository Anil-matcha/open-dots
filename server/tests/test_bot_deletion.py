import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.main import app
from app.routers import bots
from app.services.auth_service import auth_service
from app.services.computer_provider import ComputerProviderError
from app.services.storage_service import StorageService


class BotDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = StorageService(Path(self.directory.name))
        self.storage_patch = patch.object(bots, "storage_service", self.storage)
        self.storage_patch.start()
        self.provider = SimpleNamespace(
            describe=lambda bot_id: SimpleNamespace(computer_id=bot_id),
            cleanup=AsyncMock(),
        )
        self.provider_patch = patch.object(bots, "computer_provider", self.provider)
        self.provider_patch.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)),
            base_url="http://127.0.0.1",
        )
        await self.client.post("/api/v1/auth/login", json={"token": auth_service.token})

    async def asyncTearDown(self):
        await self.client.aclose()
        self.provider_patch.stop()
        self.storage_patch.stop()
        self.directory.cleanup()

    async def test_deletion_preserves_creates_and_edits_during_cleanup(self):
        original = self.storage.get_bots()
        deleted_id, edited_id = original[0]["id"], original[1]["id"]
        started, release = asyncio.Event(), asyncio.Event()

        async def cleanup(computer_id):
            started.set()
            await release.wait()

        self.provider.cleanup.side_effect = cleanup
        deleting = asyncio.create_task(self.client.delete(f"/api/v1/bots/{deleted_id}"))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            created = await self.client.post("/api/v1/bots", json={"name": "Created during cleanup"})
            edited = await self.client.put(f"/api/v1/bots/{edited_id}", json={"name": "Edited during cleanup"})
            self.assertEqual(created.status_code, 200)
            self.assertEqual(edited.status_code, 200)
        finally:
            release.set()
            deleted = await asyncio.wait_for(deleting, timeout=5)
        self.assertEqual(deleted.status_code, 200)
        # Reopen storage to verify the durable result, not just a response.
        records = {bot["id"]: bot for bot in StorageService(Path(self.directory.name)).get_bots()}
        self.assertNotIn(deleted_id, records)
        self.assertIn(created.json()["id"], records)
        self.assertEqual(records[edited_id]["name"], "Edited during cleanup")
        self.assertEqual(len(records), len(original))

    async def test_overlapping_deletions_do_not_resurrect_a_deleted_bot(self):
        original = self.storage.get_bots()
        ids = [bot["id"] for bot in original[:2]]
        started = {bot_id: asyncio.Event() for bot_id in ids}
        release = {bot_id: asyncio.Event() for bot_id in ids}

        async def cleanup(computer_id):
            started[computer_id].set()
            await release[computer_id].wait()

        self.provider.cleanup.side_effect = cleanup
        tasks = []
        try:
            for bot_id in ids:
                tasks.append(asyncio.create_task(self.client.delete(f"/api/v1/bots/{bot_id}")))
                await asyncio.wait_for(started[bot_id].wait(), timeout=5)
            for bot_id, task in zip(ids, tasks):
                release[bot_id].set()
                self.assertEqual((await asyncio.wait_for(task, timeout=5)).status_code, 200)
        finally:
            for event in release.values():
                event.set()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(self.storage.get_bots(), original[2:])

    async def test_cleanup_failure_preserves_bot_records(self):
        original = self.storage.get_bots()
        self.provider.cleanup.side_effect = ComputerProviderError("Cleanup failed")
        response = await self.client.delete(f"/api/v1/bots/{original[0]['id']}")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.storage.get_bots(), original)

    async def test_missing_bot_does_not_call_cleanup(self):
        response = await self.client.delete("/api/v1/bots/missing-bot")
        self.assertEqual(response.status_code, 404)
        self.provider.cleanup.assert_not_awaited()
