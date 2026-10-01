import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.storage_service import StorageService
from app.services.database import SCHEMA_MIGRATIONS
from app.schemas.contracts import AppSettingsSchema
from app.routers import settings as settings_router


class StorageServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.service = StorageService(self.root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_files_are_owner_only(self):
        # The main database plus any WAL sidecars must never be readable by
        # other local users: the -wal file can hold recent page copies.
        paths = [
            self.root / "open-dots.sqlite3",
            self.root / "open-dots.sqlite3-wal",
            self.root / "open-dots.sqlite3-shm",
        ]
        existing = [path for path in paths if path.exists()]
        self.assertTrue(existing, "expected at least the main database file to exist")
        for path in existing:
            self.assertEqual(
                path.stat().st_mode & 0o777, 0o600, f"{path.name} is not 0600"
            )

    def test_state_and_encrypted_settings_survive_reopen(self):
        self.service.save_bots([{"id": "bot-test", "name": "Persistent bot"}])
        self.service.add_message(
            {
                "id": "message-test",
                "thread_id": "thread-test",
                "sender": "user",
                "text": "remember this",
            }
        )
        self.service.add_approval(
            {"request_id": "request-test", "thread_id": "thread-test", "status": "pending"}
        )
        self.service.add_audit_event({"event": "test.completed", "request_id": "request-test"})
        self.service.save_settings({"model_api_key": "super-secret", "theme": "light"})

        self.service.save_settings({"model_api_key": "", "theme": "dark"})
        reopened = StorageService(self.root)

        self.assertEqual(reopened.get_bots(), [{"id": "bot-test", "name": "Persistent bot"}])
        self.assertEqual(reopened.get_messages("thread-test")[0]["text"], "remember this")
        self.assertEqual(reopened.get_approvals("thread-test")[0]["request_id"], "request-test")
        self.assertEqual(reopened.get_audit_events(10)[-1]["event"], "test.completed")
        self.assertEqual(reopened.get_settings()["model_api_key"], "super-secret")
        self.assertEqual(reopened.get_settings()["theme"], "dark")

        public = reopened.get_public_settings()
        self.assertEqual(public["model_api_key"], "")
        self.assertTrue(public["model_api_key_configured"])
        self.assertNotIn(b"super-secret", self._database_bytes())

        with sqlite3.connect(reopened.db_path) as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
        self.assertEqual(version, 2)
        with sqlite3.connect(reopened.db_path) as connection:
            owner_id = connection.execute(
                "SELECT owner_id FROM bots WHERE id = ?", ("bot-test",)
            ).fetchone()[0]
        self.assertEqual(owner_id, "local-user")

    def test_legacy_json_is_imported_and_plaintext_keys_are_scrubbed(self):
        legacy_root = self.root / "legacy"
        legacy_root.mkdir()
        legacy_secret = "legacy-secret-value"
        self._write_json(
            legacy_root,
            "bots.json",
            [{"id": "legacy-bot", "name": "Imported bot"}],
        )
        self._write_json(
            legacy_root,
            "messages.json",
            [
                {
                    "id": "legacy-message",
                    "thread_id": "legacy-thread",
                    "text": "Imported message",
                }
            ],
        )
        self._write_json(
            legacy_root,
            "settings.json",
            {
                "model_api_key": legacy_secret,
                "model_api_base_url": "https://example.test/api/v1",
                "theme": "light",
            },
        )
        self._write_json(
            legacy_root,
            "approvals.json",
            [{"request_id": "legacy-request", "thread_id": "legacy-thread"}],
        )
        self._write_json(
            legacy_root,
            "audit.json",
            [{"event": "legacy.imported", "created_at": "2026-08-20T00:00:00+00:00"}],
        )

        imported = StorageService(legacy_root)

        self.assertEqual(imported.get_bots()[0]["id"], "legacy-bot")
        self.assertEqual(imported.get_messages("legacy-thread")[0]["text"], "Imported message")
        self.assertEqual(imported.get_settings()["model_api_key"], legacy_secret)
        self.assertTrue(imported.get_public_settings()["model_api_key_configured"])
        self.assertEqual(imported.get_approvals()[0]["request_id"], "legacy-request")
        self.assertEqual(imported.get_audit_events()[0]["event"], "legacy.imported")

        scrubbed = (legacy_root / "settings.json").read_text(encoding="utf-8")
        self.assertNotIn(legacy_secret, scrubbed)
        self.assertIn('"model_api_key": ""', scrubbed)
        self.assertEqual((legacy_root / ".encryption.key").stat().st_mode & 0o777, 0o600)

        reopened = StorageService(legacy_root)
        self.assertEqual(reopened.get_settings()["model_api_key"], legacy_secret)

    def test_settings_routes_never_return_provider_credentials(self):
        self.service.save_settings({"model_api_key": "route-secret"})
        original_storage = settings_router.storage_service
        settings_router.storage_service = self.service
        try:
            fetched = asyncio.run(settings_router.get_settings())
            self.assertEqual(fetched.model_api_key, "")
            self.assertTrue(fetched.model_api_key_configured)

            saved = asyncio.run(
                settings_router.save_settings(
                    AppSettingsSchema(
                        model_api_key="",
                        model_api_base_url="https://example.test/api/v1",
                    )
                )
            )
            self.assertEqual(saved.model_api_key, "")
            self.assertTrue(saved.model_api_key_configured)
            self.assertEqual(self.service.get_settings()["model_api_key"], "route-secret")
        finally:
            settings_router.storage_service = original_storage

    def test_schema_one_is_upgraded_with_owner_columns(self):
        upgrade_root = self.root / "schema-one"
        upgrade_root.mkdir()
        db_path = upgrade_root / "open-dots.sqlite3"
        with sqlite3.connect(db_path) as connection:
            connection.executescript(SCHEMA_MIGRATIONS[1])
            connection.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-08-20T00:00:00+00:00')"
            )
            connection.execute(
                "INSERT INTO bots(id, payload) VALUES (?, ?)",
                ("old-bot", json.dumps({"id": "old-bot", "name": "Old bot"})),
            )

        upgraded = StorageService(upgrade_root)
        self.assertEqual(upgraded.get_bots()[0]["id"], "old-bot")
        with sqlite3.connect(db_path) as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            owner_id = connection.execute(
                "SELECT owner_id FROM bots WHERE id = 'old-bot'"
            ).fetchone()[0]
        self.assertEqual(version, 2)
        self.assertEqual(owner_id, "local-user")

    def _write_json(self, root: Path, name: str, value):
        (root / name).write_text(json.dumps(value), encoding="utf-8")

    def _database_bytes(self) -> bytes:
        paths = [
            self.root / "open-dots.sqlite3",
            self.root / "open-dots.sqlite3-wal",
            self.root / "open-dots.sqlite3-shm",
        ]
        return b"".join(path.read_bytes() for path in paths if path.exists())


if __name__ == "__main__":
    unittest.main()
