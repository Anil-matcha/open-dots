"""Docker-backed Playwright computer provider.

Each bot receives one short-lived container with a private browser context,
one writable workspace mount, a loopback-only ephemeral port, and an internal
token. The host API is the only component that knows the token or container
id; callers continue to use the provider-neutral computer contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import secrets
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services.computer_provider import (
    COMPUTER_CAPABILITIES,
    ComputerProviderError,
    ComputerStatus,
    computer_id_for_bot,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


DockerCommand = Callable[[Sequence[str], float], str]


@dataclass
class _RuntimeRecord:
    status: ComputerStatus
    token: str
    workspace: Path
    container_id: Optional[str] = None
    port: Optional[int] = None


class DockerComputerProvider:
    """Run browser, terminal, file, input, and screenshot actions in Docker."""

    provider_name = "docker-playwright"

    def __init__(
        self,
        *,
        docker_binary: Optional[str] = None,
        image: Optional[str] = None,
        workspace_root: Optional[Path] = None,
        cpu_limit: Optional[str] = None,
        memory_limit: Optional[str] = None,
        pids_limit: Optional[int] = None,
        start_timeout: Optional[float] = None,
        command_timeout: Optional[float] = None,
        runtime_port: Optional[int] = None,
        seccomp_profile: Optional[Path] = None,
        docker_command: Optional[DockerCommand] = None,
    ):
        self.docker_binary = docker_binary or settings.COMPUTER_DOCKER_BINARY
        self.image = image or settings.COMPUTER_DOCKER_IMAGE
        self.workspace_root = (workspace_root or settings.COMPUTER_DOCKER_WORKSPACE_ROOT).expanduser().resolve()
        self.cpu_limit = cpu_limit or settings.COMPUTER_DOCKER_CPU_LIMIT
        self.memory_limit = memory_limit or settings.COMPUTER_DOCKER_MEMORY_LIMIT
        self.pids_limit = pids_limit or settings.COMPUTER_DOCKER_PIDS_LIMIT
        self.start_timeout = start_timeout or settings.COMPUTER_DOCKER_START_TIMEOUT
        self.command_timeout = command_timeout or settings.COMPUTER_DOCKER_COMMAND_TIMEOUT
        self.runtime_port = runtime_port or settings.COMPUTER_DOCKER_RUNTIME_PORT
        self.seccomp_profile = (seccomp_profile or settings.COMPUTER_DOCKER_SECCOMP_PROFILE).expanduser().resolve()
        self._docker_command = docker_command or self._run_docker
        self._runtimes: Dict[str, _RuntimeRecord] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _new_status(bot_id: str, generation: int = 0) -> ComputerStatus:
        return ComputerStatus(
            computer_id=computer_id_for_bot(bot_id),
            bot_id=bot_id.strip(),
            provider=DockerComputerProvider.provider_name,
            state="stopped",
            health="unknown",
            width=1280,
            height=720,
            fps=10,
            generation=generation,
            capabilities=COMPUTER_CAPABILITIES,
            updated_at=_now(),
        )

    @staticmethod
    def _touch(status: ComputerStatus, operation: str) -> ComputerStatus:
        status.last_operation = operation
        status.updated_at = _now()
        return status

    def describe(self, bot_id: str) -> ComputerStatus:
        computer_id = computer_id_for_bot(bot_id)
        record = self._runtimes.get(computer_id)
        return record.status if record else self._new_status(bot_id)

    async def reconcile(self, bot_id: str) -> ComputerStatus:
        record = await self._recover_container(computer_id_for_bot(bot_id), force=True)
        return record.status if record else self._new_status(bot_id)

    def get_or_create(self, bot_id: str) -> ComputerStatus:
        computer_id = computer_id_for_bot(bot_id)
        existing = self._runtimes.get(computer_id)
        if existing:
            return existing.status

        workspace = (self.workspace_root / computer_id).resolve()
        if self.workspace_root not in workspace.parents:
            raise ComputerProviderError("The computer workspace escaped its configured root.")
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o700)
        status = self._new_status(bot_id, generation=1)
        self._runtimes[computer_id] = _RuntimeRecord(
            status=status,
            token=secrets.token_urlsafe(32),
            workspace=workspace,
        )
        return status

    def _record_for(self, computer_id: str) -> _RuntimeRecord:
        record = self._runtimes.get(computer_id)
        if record is None:
            raise ComputerProviderError("The requested computer does not exist.")
        return record

    def _active_record(self, computer_id: str) -> _RuntimeRecord:
        record = self._record_for(computer_id)
        if record.status.state not in {"running", "paused"}:
            raise ComputerProviderError(
                f"Computer is not active; current state is {record.status.state}."
            )
        if not record.container_id or not record.port:
            raise ComputerProviderError("Computer runtime connection is unavailable.")
        return record

    def _run_docker(self, args: Sequence[str], timeout: float) -> str:
        try:
            completed = subprocess.run(
                [self.docker_binary, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ComputerProviderError(
                f"Docker executable not found: {self.docker_binary}."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ComputerProviderError("Docker command timed out.") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Docker command failed.").strip()
            raise ComputerProviderError(f"Docker command failed: {detail[:600]}")
        return completed.stdout.strip()

    async def _docker(self, args: Sequence[str], timeout: Optional[float] = None) -> str:
        return await asyncio.to_thread(
            self._docker_command,
            tuple(args),
            timeout if timeout is not None else self.command_timeout,
        )

    async def _recover_container(self, computer_id: str, *, force: bool = False) -> Optional[_RuntimeRecord]:
        record = self._runtimes.get(computer_id)
        if record and (record.container_id or not force):
            return record
        name = f"open-dots-computer-{computer_id[-70:]}"
        try:
            raw = await self._docker(["inspect", "--format", "{{json .}}", name])
            info = json.loads(raw)
            labels = info.get("Config", {}).get("Labels", {}) or {}
            env = info.get("Config", {}).get("Env", []) or []
            values = dict(item.split("=", 1) for item in env if "=" in item)
            token = values.get("COMPUTER_TOKEN")
            bot_id = labels.get("open-dots.bot-id")
            if not token or not bot_id:
                return record
            state_info = info.get("State", {}) or {}
            paused = bool(state_info.get("Paused"))
            running = bool(state_info.get("Running"))
            status = self._new_status(bot_id, generation=1)
            status.state = "paused" if paused else "running" if running else "stopped"
            status.health = "healthy" if running else "unknown"
            port_data = ((info.get("NetworkSettings", {}).get("Ports", {}) or {}).get(f"{self.runtime_port}/tcp") or [])
            port = int(port_data[0]["HostPort"]) if port_data else None
            workspace = (self.workspace_root / computer_id).resolve()
            record = _RuntimeRecord(status, token, workspace, info.get("Id"), port)
            self._runtimes[computer_id] = record
            return record
        except (ComputerProviderError, ValueError, KeyError, TypeError, IndexError):
            return record

    def _container_name(self, record: _RuntimeRecord) -> str:
        return f"open-dots-computer-{record.status.computer_id[-70:]}"

    async def _launch(self, record: _RuntimeRecord) -> None:
        record.workspace.mkdir(parents=True, exist_ok=True)
        # The runtime token is the key to arbitrary in-container shell. Docker CLI
        # arguments are visible to any local user via `ps`, so pass the secret
        # through a 0600 env file instead of `--env` on the command line.
        env_fd, env_path = tempfile.mkstemp(prefix="open-dots-computer-", suffix=".env")
        try:
            try:
                with os.fdopen(env_fd, "w") as env_file:
                    env_file.write(f"COMPUTER_TOKEN={record.token}\n")
            except Exception:
                # fdopen takes ownership of the fd only on success; close it here
                # so a failure cannot leak the descriptor.
                os.close(env_fd)
                raise
            os.chmod(env_path, 0o600)
            args = [
                "run",
                "-d",
                "--rm",
                "--init",
                "--name",
                self._container_name(record),
                "--label",
                "open-dots.runtime=computer",
                "--label",
                f"open-dots.computer-id={record.status.computer_id}",
                "--label",
                f"open-dots.bot-id={record.status.bot_id}",
                "--publish",
                f"127.0.0.1::{self.runtime_port}",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,nosuid,size=512m",
                "--tmpfs",
                "/home/pwuser:rw,nosuid,size=1g",
            "--mount",
            f"type=bind,src={record.workspace},dst=/workspace",
            "--cpus",
            self.cpu_limit,
            "--memory",
            self.memory_limit,
            "--pids-limit",
            str(self.pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--shm-size",
            "2g",
            "--user",
            "pwuser",
            "--env-file",
            env_path,
            "--env",
            f"COMPUTER_ID={record.status.computer_id}",
            "--env",
            f"PORT={self.runtime_port}",
            "--env",
            "WORKSPACE=/workspace",
            "--env",
            f"COMPUTER_COMMAND_TIMEOUT={int(self.command_timeout * 1000)}",
            self.image,
        ]
            if self.seccomp_profile.is_file():
                args[-1:-1] = ["--security-opt", f"seccomp={self.seccomp_profile}"]

            output = await self._docker(args, timeout=self.start_timeout)
            container_id = output.splitlines()[-1].strip() if output else ""
            if not container_id:
                raise ComputerProviderError("Docker did not return a computer container id.")
            record.container_id = container_id

            ports = await self._docker(["port", container_id, f"{self.runtime_port}/tcp"])
            matches = re.findall(r":(\d+)", ports)
            if not matches:
                raise ComputerProviderError("Docker did not publish a computer runtime port.")
            record.port = int(matches[-1])
        finally:
            # Docker reads the env file at container creation time, so it is safe
            # to remove immediately after `docker run` returns.
            try:
                os.unlink(env_path)
            except OSError:
                pass

    async def _remove_container(self, record: _RuntimeRecord, suppress_errors: bool = True) -> None:
        if not record.container_id:
            record.port = None
            return
        container_id = record.container_id
        try:
            await self._docker(["rm", "-f", container_id])
        except ComputerProviderError:
            if not suppress_errors:
                raise
        finally:
            record.container_id = None
            record.port = None

    async def _request(
        self,
        record: _RuntimeRecord,
        method: str,
        route: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not record.port:
            raise ComputerProviderError("Computer runtime is not connected.")
        url = f"http://127.0.0.1:{record.port}{route}"
        try:
            async with httpx.AsyncClient(
                timeout=max(2.0, self.command_timeout + 5.0),
                headers={"x-computer-token": record.token},
            ) as client:
                response = await client.request(method, url, json=payload)
        except httpx.HTTPError as exc:
            raise ComputerProviderError("Computer runtime did not respond.") from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise ComputerProviderError("Computer runtime returned invalid JSON.") from exc
        if response.status_code >= 400:
            raise ComputerProviderError(str(result.get("error") or "Computer runtime action failed."))
        if not isinstance(result, dict):
            raise ComputerProviderError("Computer runtime returned an invalid payload.")
        return result

    async def _wait_until_ready(self, record: _RuntimeRecord) -> Dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.start_timeout
        last_error = "Computer runtime did not become ready."
        while asyncio.get_running_loop().time() < deadline:
            try:
                health = await self._request(record, "GET", "/health")
                if health.get("status") == "healthy":
                    return health
            except ComputerProviderError as exc:
                last_error = str(exc)
            await asyncio.sleep(0.2)
        raise ComputerProviderError(last_error)

    async def create(self, bot_id: str) -> ComputerStatus:
        return self.get_or_create(bot_id)

    async def start(self, computer_id: str) -> ComputerStatus:
        await self._recover_container(computer_id, force=True)
        async with self._lock:
            record = self._record_for(computer_id)
            status = record.status
            if status.state == "running":
                return self._touch(status, "start")
            if status.state == "paused" and record.container_id:
                await self._docker(["unpause", record.container_id])
                status.state = "running"
                status.health = "healthy"
                return self._touch(status, "start")

            status.state = "starting"
            status.health = "unknown"
            self._touch(status, "start")
            try:
                record.token = secrets.token_urlsafe(32)
                await self._launch(record)
                health = await self._wait_until_ready(record)
            except Exception as exc:
                await self._remove_container(record)
                status.state = "error"
                status.health = "unhealthy"
                self._touch(status, "start")
                if isinstance(exc, ComputerProviderError):
                    raise
                raise ComputerProviderError(str(exc)) from exc

            status.state = "running"
            status.health = "healthy"
            status.width = int(health.get("width") or status.width)
            status.height = int(health.get("height") or status.height)
            return self._touch(status, "start")

    async def stop(self, computer_id: str) -> ComputerStatus:
        await self._recover_container(computer_id, force=True)
        async with self._lock:
            record = self._record_for(computer_id)
            await self._remove_container(record)
            status = record.status
            status.state = "stopped"
            status.health = "unknown"
            status.frame_id = None
            return self._touch(status, "stop")

    async def pause(self, computer_id: str) -> ComputerStatus:
        await self._recover_container(computer_id, force=True)
        async with self._lock:
            record = self._active_record(computer_id)
            if record.status.state == "paused":
                return self._touch(record.status, "pause")
            await self._docker(["pause", record.container_id or ""])
            record.status.state = "paused"
            record.status.health = "healthy"
            return self._touch(record.status, "pause")

    async def reset(self, computer_id: str) -> ComputerStatus:
        await self._recover_container(computer_id, force=True)
        async with self._lock:
            record = self._record_for(computer_id)
            await self._remove_container(record)
            status = record.status
            status.generation += 1
            status.state = "stopped"
            status.health = "unknown"
            status.frame_id = None
            status.url = None
            record.token = secrets.token_urlsafe(32)
            return self._touch(status, "reset")

    async def health(self, computer_id: str) -> ComputerStatus:
        await self._recover_container(computer_id, force=True)
        record = self._record_for(computer_id)
        status = record.status
        if status.state not in {"running", "paused"} or not record.container_id:
            status.health = "unknown"
            return self._touch(status, "health")
        try:
            result = await self._request(record, "GET", "/health")
            status.health = "healthy" if result.get("status") == "healthy" else "unhealthy"
            status.width = int(result.get("width") or status.width)
            status.height = int(result.get("height") or status.height)
        except ComputerProviderError:
            status.health = "unhealthy"
        return self._touch(status, "health")

    async def browser_navigate(self, computer_id: str, url: str) -> Dict[str, Any]:
        await self._recover_container(computer_id, force=True)
        record = self._active_record(computer_id)
        if not isinstance(url, str) or len(url.strip()) > 2048:
            raise ComputerProviderError("A browser URL is required and must be at most 2048 characters.")
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ComputerProviderError("Browser navigation only accepts absolute HTTP(S) URLs.")
        result = await self._request(record, "POST", "/navigate", {"url": url.strip()})
        record.status.url = result.get("url") or url.strip()
        self._touch(record.status, "browser.navigate")
        return {"computer_id": computer_id, "provider": self.provider_name, **result}

    async def terminal_execute(self, computer_id: str, command: str) -> Dict[str, Any]:
        await self._recover_container(computer_id, force=True)
        record = self._active_record(computer_id)
        if not isinstance(command, str) or not command.strip():
            raise ComputerProviderError("A terminal command is required.")
        if len(command) > 4000:
            raise ComputerProviderError("Terminal commands must be at most 4000 characters.")
        result = await self._request(record, "POST", "/terminal", {"command": command})
        self._touch(record.status, "terminal.exec")
        return {"computer_id": computer_id, "provider": self.provider_name, **result}

    async def files_list(self, computer_id: str, path: str = "/workspace") -> Dict[str, Any]:
        await self._recover_container(computer_id, force=True)
        record = self._active_record(computer_id)
        if not isinstance(path, str) or len(path) > 512 or not path.strip().startswith("/"):
            raise ComputerProviderError("Computer file paths must be absolute and at most 512 characters.")
        result = await self._request(record, "POST", "/files", {"path": path.strip()})
        self._touch(record.status, "files.list")
        return {"computer_id": computer_id, "provider": self.provider_name, **result}

    async def screenshot(self, computer_id: str) -> Dict[str, Any]:
        await self._recover_container(computer_id, force=True)
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
                "message": "Start the Docker computer before requesting a screen frame.",
            }
        result = await self._request(record, "POST", "/screenshot")
        record.status.frame_id = result.get("frame_id")
        record.status.width = int(result.get("width") or record.status.width)
        record.status.height = int(result.get("height") or record.status.height)
        self._touch(record.status, "screenshot")
        return {"computer_id": computer_id, "provider": self.provider_name, "available": True, **result}

    async def send_input(self, computer_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        await self._recover_container(computer_id, force=True)
        record = self._active_record(computer_id)
        if not isinstance(event, dict):
            raise ComputerProviderError("Computer input must be a JSON object.")
        result = await self._request(record, "POST", "/input", {"event": event})
        self._touch(record.status, "input")
        return {"computer_id": computer_id, "provider": self.provider_name, **result}

    async def cleanup(self, computer_id: str) -> Dict[str, Any]:
        await self._recover_container(computer_id, force=True)
        async with self._lock:
            record = self._runtimes.get(computer_id)
            if record is None:
                return {
                    "computer_id": computer_id,
                    "bot_id": computer_id.removeprefix("computer-"),
                    "provider": self.provider_name,
                    "state": "cleaned",
                    "generation": 0,
                    "workspace_preserved": True,
                }
            await self._remove_container(record)
            self._runtimes.pop(computer_id, None)
            return {
                "computer_id": computer_id,
                "bot_id": record.status.bot_id,
                "provider": self.provider_name,
                "state": "cleaned",
                "generation": record.status.generation,
                "workspace_preserved": True,
            }
