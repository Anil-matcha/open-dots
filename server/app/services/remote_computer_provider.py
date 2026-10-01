"""HTTP-backed computer provider for hosted or separately managed runtimes.

The remote adapter deliberately speaks a small, provider-neutral REST contract.
It lets a deployment use a hosted browser/desktop service without putting that
service's SDK in the application or bypassing the action gateway.

Expected remote routes are rooted at ``COMPUTER_REMOTE_BASE_URL``::

    POST   /computers
    POST   /computers/{id}/start
    POST   /computers/{id}/stop
    POST   /computers/{id}/pause
    POST   /computers/{id}/reset
    GET    /computers/{id}/health
    POST   /computers/{id}/navigate
    POST   /computers/{id}/terminal
    POST   /computers/{id}/files
    POST   /computers/{id}/screenshot
    POST   /computers/{id}/input
    DELETE /computers/{id}

The adapter only stores an opaque remote id and normalized status locally. API
keys stay in process configuration and are never included in status or audit
payloads.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import httpx

from app.config import settings
from app.services.computer_provider import (
    COMPUTER_CAPABILITIES,
    ComputerProviderError,
    ComputerStatus,
    ComputerState,
    computer_id_for_bot,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _RemoteRecord:
    status: ComputerStatus
    remote_id: Optional[str] = None


class RemoteComputerProvider:
    """Use an authenticated remote computer service through a small REST API."""

    provider_name = "remote-api"

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        auth_header: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        timeout: Optional[float] = None,
        start_timeout: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
    ):
        self.base_url = (base_url if base_url is not None else settings.COMPUTER_REMOTE_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.COMPUTER_REMOTE_API_KEY
        self.auth_header = (auth_header or settings.COMPUTER_REMOTE_AUTH_HEADER).strip()
        self.auth_scheme = (auth_scheme if auth_scheme is not None else settings.COMPUTER_REMOTE_AUTH_SCHEME).strip()
        self.timeout = timeout or settings.COMPUTER_REMOTE_TIMEOUT
        self.start_timeout = start_timeout or settings.COMPUTER_REMOTE_START_TIMEOUT
        self.width = width or settings.COMPUTER_REMOTE_WIDTH
        self.height = height or settings.COMPUTER_REMOTE_HEIGHT
        self.fps = fps or settings.COMPUTER_REMOTE_FPS
        self._computers: Dict[str, _RemoteRecord] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _new_status(
        bot_id: str,
        *,
        generation: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 10,
    ) -> ComputerStatus:
        return ComputerStatus(
            computer_id=computer_id_for_bot(bot_id),
            bot_id=bot_id.strip(),
            provider=RemoteComputerProvider.provider_name,
            state="stopped",
            health="unknown",
            width=width,
            height=height,
            fps=fps,
            generation=generation,
            capabilities=COMPUTER_CAPABILITIES,
            updated_at=_now(),
        )

    @staticmethod
    def _touch(status: ComputerStatus, operation: str) -> ComputerStatus:
        status.last_operation = operation
        status.updated_at = _now()
        return status

    @staticmethod
    def _state(value: Any, fallback: ComputerState) -> ComputerState:
        normalized = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "created": "stopped",
            "ready": "running",
            "active": "running",
            "live": "running",
            "failed": "error",
            "offline": "stopped",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in {"stopped", "starting", "running", "paused", "resetting", "error"}:
            return normalized  # type: ignore[return-value]
        return fallback

    @staticmethod
    def _health(value: Any, fallback: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"healthy", "ready", "ok", "online"}:
            return "healthy"
        if normalized in {"unhealthy", "failed", "error", "offline"}:
            return "unhealthy"
        if normalized in {"unknown", "", "starting", "pending"}:
            return "unknown"
        return fallback

    @staticmethod
    def _payload(response: Dict[str, Any]) -> Dict[str, Any]:
        nested = response.get("data")
        return nested if isinstance(nested, dict) else response

    @staticmethod
    def _coerce_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        """Best-effort int() over third-party JSON: a hostile or buggy remote
        must not turn into an unhandled ValueError (and a 500) here."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _apply_status(self, status: ComputerStatus, payload: Dict[str, Any]) -> ComputerStatus:
        data = self._payload(payload)
        status.state = self._state(data.get("state") or data.get("status"), status.state)
        status.health = self._health(data.get("health") or data.get("health_status"), status.health)
        if data.get("width") is not None:
            width = self._coerce_int(data["width"])
            if width is not None:
                status.width = width
        if data.get("height") is not None:
            height = self._coerce_int(data["height"])
            if height is not None:
                status.height = height
        if data.get("fps") is not None:
            fps = self._coerce_int(data["fps"])
            if fps is not None:
                status.fps = fps
        if data.get("generation") is not None:
            generation = self._coerce_int(data["generation"])
            if generation is not None:
                status.generation = max(status.generation, generation)
        if data.get("frame_id") is not None:
            status.frame_id = str(data["frame_id"])
        if data.get("url") is not None:
            status.url = str(data["url"])
        return status

    def describe(self, bot_id: str) -> ComputerStatus:
        computer_id = computer_id_for_bot(bot_id)
        record = self._computers.get(computer_id)
        return record.status if record else self._new_status(
            bot_id,
            width=self.width,
            height=self.height,
            fps=self.fps,
        )

    def get_or_create(self, bot_id: str) -> ComputerStatus:
        computer_id = computer_id_for_bot(bot_id)
        existing = self._computers.get(computer_id)
        if existing:
            return existing.status
        status = self._new_status(
            bot_id,
            generation=1,
            width=self.width,
            height=self.height,
            fps=self.fps,
        )
        self._computers[computer_id] = _RemoteRecord(status=status)
        return status

    def _record_for(self, computer_id: str) -> _RemoteRecord:
        record = self._computers.get(computer_id)
        if record is None:
            raise ComputerProviderError("The requested computer does not exist.")
        return record

    def _active_record(self, computer_id: str) -> _RemoteRecord:
        record = self._record_for(computer_id)
        if record.status.state not in {"running", "paused"}:
            raise ComputerProviderError(
                f"Computer is not active; current state is {record.status.state}."
            )
        if not record.remote_id:
            raise ComputerProviderError("Remote computer connection is unavailable.")
        return record

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ComputerProviderError(
                "COMPUTER_REMOTE_API_KEY is required when COMPUTER_PROVIDER=remote."
            )
        if not self.auth_header:
            raise ComputerProviderError("COMPUTER_REMOTE_AUTH_HEADER cannot be empty.")
        value = f"{self.auth_scheme} {self.api_key}".strip() if self.auth_scheme else self.api_key
        return {
            self.auth_header: value,
            "accept": "application/json",
            "content-type": "application/json",
        }

    def _url(self, route: str) -> str:
        if not self.base_url:
            raise ComputerProviderError(
                "COMPUTER_REMOTE_BASE_URL is required when COMPUTER_PROVIDER=remote."
            )
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ComputerProviderError("COMPUTER_REMOTE_BASE_URL must be an absolute HTTP(S) URL.")
        return f"{self.base_url}/{route.lstrip('/')}"

    async def _request(
        self,
        method: str,
        route: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
        ok_if_not_found: bool = False,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=max(2.0, min(timeout or self.timeout, 120.0)),
                headers=self._headers(),
            ) as client:
                response = await client.request(method, self._url(route), json=payload)
        except httpx.HTTPError as exc:
            raise ComputerProviderError("Remote computer API did not respond.") from exc

        if response.status_code == 204:
            return {}
        if response.status_code == 404 and ok_if_not_found:
            # Idempotent delete: already gone on the remote side is the
            # desired end state.
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            raise ComputerProviderError("Remote computer API returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise ComputerProviderError("Remote computer API returned an invalid payload.")
        if response.status_code >= 400:
            detail = body.get("error") or body.get("message") or "Remote computer API request failed."
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("detail") or str(detail)
            raise ComputerProviderError(str(detail)[:600])
        return body

    def _remote_path(self, remote_id: str, suffix: str = "") -> str:
        encoded = quote(remote_id, safe="")
        return f"/computers/{encoded}{suffix}"

    def _set_remote_id(self, record: _RemoteRecord, payload: Dict[str, Any]) -> None:
        data = self._payload(payload)
        remote_id = data.get("computer_id") or data.get("id") or data.get("session_id")
        if remote_id is not None:
            record.remote_id = str(remote_id)

    async def _ensure_remote(self, record: _RemoteRecord) -> Dict[str, Any]:
        if record.remote_id:
            return {}
        payload = await self._request(
            "POST",
            "/computers",
            {
                "computer_id": record.status.computer_id,
                "bot_id": record.status.bot_id,
                "width": record.status.width,
                "height": record.status.height,
                "fps": record.status.fps,
            },
            timeout=self.start_timeout,
        )
        self._set_remote_id(record, payload)
        if not record.remote_id:
            # A simple remote gateway may use the stable id supplied by us and
            # omit it from a successful create response.
            record.remote_id = record.status.computer_id
        self._apply_status(record.status, payload)
        return payload

    async def create(self, bot_id: str) -> ComputerStatus:
        async with self._lock:
            status = self.get_or_create(bot_id)
            record = self._record_for(status.computer_id)
            payload = await self._ensure_remote(record)
            self._apply_status(record.status, payload)
            return self._touch(record.status, "create")

    async def start(self, computer_id: str) -> ComputerStatus:
        async with self._lock:
            record = self._record_for(computer_id)
            status = record.status
            if status.state == "running" and record.remote_id:
                return self._touch(status, "start")
            status.state = "starting"
            status.health = "unknown"
            self._touch(status, "start")
            try:
                await self._ensure_remote(record)
                payload = await self._request(
                    "POST",
                    self._remote_path(record.remote_id or "", "/start"),
                    {},
                    timeout=self.start_timeout,
                )
                self._apply_status(status, payload)
            except ComputerProviderError:
                status.state = "error"
                status.health = "unhealthy"
                self._touch(status, "start")
                raise
            if status.state == "starting":
                status.state = "running"
            if status.health == "unknown":
                status.health = "healthy"
            return self._touch(status, "start")

    async def _lifecycle(self, computer_id: str, operation: str) -> ComputerStatus:
        async with self._lock:
            record = self._record_for(computer_id)
            await self._ensure_remote(record)
            payload = await self._request(
                "POST",
                self._remote_path(record.remote_id or "", f"/{operation}"),
                {},
            )
            self._apply_status(record.status, payload)
            if operation == "stop":
                record.status.state = "stopped"
                record.status.health = "unknown"
                record.status.frame_id = None
            elif operation == "pause":
                record.status.state = "paused"
            elif operation == "reset":
                record.status.generation += 1
                record.status.state = "stopped"
                record.status.health = "unknown"
                record.status.frame_id = None
                record.status.url = None
            return self._touch(record.status, operation)

    async def stop(self, computer_id: str) -> ComputerStatus:
        return await self._lifecycle(computer_id, "stop")

    async def pause(self, computer_id: str) -> ComputerStatus:
        record = self._active_record(computer_id)
        if record.status.state == "paused":
            return self._touch(record.status, "pause")
        return await self._lifecycle(computer_id, "pause")

    async def reset(self, computer_id: str) -> ComputerStatus:
        return await self._lifecycle(computer_id, "reset")

    async def health(self, computer_id: str) -> ComputerStatus:
        record = self._record_for(computer_id)
        if not record.remote_id:
            return self._touch(record.status, "health")
        payload = await self._request("GET", self._remote_path(record.remote_id, "/health"))
        self._apply_status(record.status, payload)
        if record.status.health == "unknown":
            record.status.health = "healthy" if record.status.state in {"running", "paused"} else "unknown"
        return self._touch(record.status, "health")

    async def browser_navigate(self, computer_id: str, url: str) -> Dict[str, Any]:
        record = self._active_record(computer_id)
        if not isinstance(url, str) or len(url.strip()) > 2048:
            raise ComputerProviderError("A browser URL is required and must be at most 2048 characters.")
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ComputerProviderError("Browser navigation only accepts absolute HTTP(S) URLs.")
        result = await self._request(
            "POST",
            self._remote_path(record.remote_id or "", "/navigate"),
            {"url": url.strip()},
        )
        data = self._payload(result)
        record.status.url = str(data.get("url") or url.strip())
        self._touch(record.status, "browser.navigate")
        return {"computer_id": computer_id, "provider": self.provider_name, **data}

    async def terminal_execute(self, computer_id: str, command: str) -> Dict[str, Any]:
        record = self._active_record(computer_id)
        if not isinstance(command, str) or not command.strip():
            raise ComputerProviderError("A terminal command is required.")
        if len(command) > 4000:
            raise ComputerProviderError("Terminal commands must be at most 4000 characters.")
        result = await self._request(
            "POST",
            self._remote_path(record.remote_id or "", "/terminal"),
            {"command": command},
        )
        self._touch(record.status, "terminal.exec")
        return {"computer_id": computer_id, "provider": self.provider_name, **self._payload(result)}

    async def files_list(self, computer_id: str, path: str = "/workspace") -> Dict[str, Any]:
        record = self._active_record(computer_id)
        if not isinstance(path, str) or len(path) > 512 or not path.strip().startswith("/"):
            raise ComputerProviderError("Computer file paths must be absolute and at most 512 characters.")
        result = await self._request(
            "POST",
            self._remote_path(record.remote_id or "", "/files"),
            {"path": path.strip()},
        )
        self._touch(record.status, "files.list")
        return {"computer_id": computer_id, "provider": self.provider_name, **self._payload(result)}

    async def screenshot(self, computer_id: str) -> Dict[str, Any]:
        record = self._record_for(computer_id)
        if record.status.state not in {"running", "paused"}:
            return {
                "computer_id": computer_id,
                "provider": self.provider_name,
                "available": False,
                "frame_id": None,
                "format": "jpeg",
                "width": record.status.width,
                "height": record.status.height,
                "state": record.status.state,
                "data": None,
                "message": "Start the remote computer before requesting a screen frame.",
            }
        result = await self._request(
            "POST",
            self._remote_path(record.remote_id or "", "/screenshot"),
        )
        data = self._payload(result)
        self._apply_status(record.status, data)
        self._touch(record.status, "screenshot")
        return {
            "computer_id": computer_id,
            "provider": self.provider_name,
            "available": True,
            **data,
        }

    async def send_input(self, computer_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        record = self._active_record(computer_id)
        if not isinstance(event, dict):
            raise ComputerProviderError("Computer input must be a JSON object.")
        result = await self._request(
            "POST",
            self._remote_path(record.remote_id or "", "/input"),
            {"event": event},
        )
        self._touch(record.status, "input")
        return {"computer_id": computer_id, "provider": self.provider_name, **self._payload(result)}

    async def cleanup(self, computer_id: str) -> Dict[str, Any]:
        async with self._lock:
            record = self._computers.get(computer_id)
            if record is None:
                # Already cleaned (or never created): treat as a successful no-op so
                # delete flows stay idempotent instead of failing with 409.
                return {
                    "computer_id": computer_id,
                    "bot_id": computer_id.removeprefix("computer-"),
                    "provider": self.provider_name,
                    "state": "cleaned",
                    "generation": 0,
                }
            if record.remote_id:
                await self._request(
                    "DELETE", self._remote_path(record.remote_id), ok_if_not_found=True
                )
            self._computers.pop(computer_id, None)
            return {
                "computer_id": computer_id,
                "bot_id": record.status.bot_id,
                "provider": self.provider_name,
                "state": "cleaned",
                "generation": record.status.generation,
            }
