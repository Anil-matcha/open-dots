import json
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app import telegram_bot
from app.db.models.task import Tasks


@pytest.fixture
def bot_api():
    """Owned loopback HTTP fixture implementing Telegram's plain-text limit."""
    messages = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            if self.path.endswith("/getMe"):
                payload = {"ok": True, "result": {"id": 123, "is_bot": True, "first_name": "Owned", "username": "owned_bot"}}
                status = 200
            else:
                assert self.path.endswith("/sendMessage")
                text = data["text"][0]
                if not 0 < len(text) <= 4096:
                    payload = {"ok": False, "error_code": 400, "description": "Bad Request: message is too long"}
                    status = 400
                else:
                    messages.append(text)
                    payload = {"ok": True, "result": {"message_id": len(messages), "date": 1700000000, "chat": {"id": 1, "type": "private"}, "text": text}}
                    status = 200
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/bot", messages
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


@pytest.mark.parametrize("status, output", [
    ("succeeded", "short report"),
    ("succeeded", "report\n" * 1300),
    ("succeeded", "界" * 5000),
    ("failed", "upstream error\n" * 500),
    ("succeeded", ""),
], ids=["short-success", "long-report", "unicode-report", "long-failure", "empty-success"])
async def test_completed_task_delivers_all_output(
    db_session: AsyncSession, user_id: str, monkeypatch, bot_api, status: str, output: str
):
    task = Tasks(user_id=user_id, provider="claude", box_id="owned-box", prompt_text="report",
                 status=status, result=output if status == "succeeded" else None,
                 error=output if status == "failed" else None)
    db_session.add(task)
    await db_session.flush()

    @asynccontextmanager
    async def session():
        yield db_session

    monkeypatch.setattr(telegram_bot, "AsyncSessionLocal", session)
    base_url, messages = bot_api
    async with Bot(token="123:owned-fixture", base_url=base_url) as bot:
        await telegram_bot._poll_task(bot, 1, task.id)
    expected = (output or "Task completed.") if status == "succeeded" else f"Task failed: {output}"
    assert "".join(messages) == expected
    assert all(0 < len(message) <= 4096 for message in messages)
