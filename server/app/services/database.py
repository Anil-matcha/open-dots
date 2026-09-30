"""SQLite connection and migration helpers for local durable state."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Iterator, Optional


SCHEMA_MIGRATIONS = {
    1: """
        CREATE TABLE IF NOT EXISTS bots (
            id TEXT PRIMARY KEY,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            is_secret INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS approvals (
            request_id TEXT PRIMARY KEY,
            thread_id TEXT,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_approvals_thread ON approvals(thread_id);
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at);
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            bot_id TEXT,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            status TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS connections (
            id TEXT PRIMARY KEY,
            connector TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            bot_id TEXT,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS storage_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """,
    2: """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO users(id, username, role, created_at)
        VALUES ('local-user', 'local', 'owner', datetime('now'));
    """,
}

OWNER_TABLES = (
    "bots",
    "messages",
    "settings",
    "approvals",
    "audit_events",
    "threads",
    "tasks",
    "connections",
    "memories",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Small SQLite wrapper with WAL mode and explicit schema versions."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            # Create the file with 0600 from the start so there is no
            # world-readable window before the chmod below.
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        self._migrate()
        self._restrict_files()

    def _restrict_files(self) -> None:
        """Keep the database and its WAL sidecars readable only by the owner.

        SQLite creates the -wal/-shm files with the process umask on first
        write, so they must be restricted explicitly alongside the main file.
        """
        for candidate in (self.path, self.path.parent / f"{self.path.name}-wal", self.path.parent / f"{self.path.name}-shm"):
            try:
                if candidate.exists():
                    os.chmod(candidate, 0o600)
            except OSError:
                pass

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._restrict_files()

    def _migrate(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row[0]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in sorted(SCHEMA_MIGRATIONS.items()):
                if version in applied:
                    continue
                connection.executescript(sql)
                if version == 2:
                    self._add_owner_columns(connection)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, _now()),
                )

    @staticmethod
    def _add_owner_columns(connection: sqlite3.Connection) -> None:
        for table in OWNER_TABLES:
            columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "owner_id" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'local-user'"
                )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_owner ON {table}(owner_id)"
            )

    def get_meta(self, key: str) -> Optional[str]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM storage_meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO storage_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
