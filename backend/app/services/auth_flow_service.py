import json
import re
import time
from dataclasses import dataclass

from boat_sdk.exceptions import ApiException

from app.services.box_operations import ascii_box_service

POLL_INTERVAL_SECONDS = 2
URL_POLL_ATTEMPTS = 15
CODE_POLL_ATTEMPTS = 15
DEVICE_CODE_POLL_ATTEMPTS = 15
# The device-flow login process waits for the user to approve it in their
# own browser, which can take a while, so this gets a much longer budget
# than the other polls.
DEVICE_COMPLETION_POLL_ATTEMPTS = 150

RUNNABLE_BOX_STATES = {"ready", "running", "idle"}

PROVIDERS = {
    "claude": {
        "login_command": "claude auth login",
        "credential_path": ".claude/.credentials.json",
        "abandon_timeout_seconds": 300,
    },
    "github": {
        "login_command": (
            "gh auth login --hostname github.com --git-protocol https --web"
        ),
        # Makes the "open in your browser" step a no-op instead of trying
        # to launch a real browser inside the sandbox.
        "env": {"GH_BROWSER": "true"},
        "credential_path": ".config/gh/hosts.yml",
        "abandon_timeout_seconds": 300,
    },
}


@dataclass
class DeviceLogin:
    url: str
    code: str


class UnsupportedProviderError(Exception):
    pass


class LoginTimeoutError(Exception):
    pass


class LoginFailedError(Exception):
    pass


class BoxNotRunningError(Exception):
    pass


class BoxCommandError(Exception):
    pass


def _session_name(box_id: str, provider: str) -> str:
    return f"auth_{provider}_{box_id}"


def _ensure_box_running(box_id: str) -> None:
    try:
        result = ascii_box_service.get_box(box_id)
    except ApiException as exc:
        raise BoxCommandError(
            f"Could not reach box {box_id}: {exc.status} {exc.reason}"
        ) from exc

    if result.sandbox.state not in RUNNABLE_BOX_STATES:
        try:
            ascii_box_service.resume_box(box_id)
        except ApiException as exc:
            raise BoxCommandError(
                f"Could not resume box {box_id}: {exc.status} {exc.reason}"
            ) from exc


def _run(box_id: str, command: str) -> str:
    try:
        result = ascii_box_service.run_command(box_id, command)
    except ApiException as exc:
        raise BoxCommandError(
            f"Command failed on box {box_id}: {exc.status} {exc.reason}"
        ) from exc

    parsed = json.loads(result.to_json())
    if parsed.get("success") is False:
        raise BoxCommandError(
            f"Command failed on box {box_id}: {parsed.get('stderr') or parsed.get('signal')}"
        )
    return parsed.get("stdout") or ""


def _provider_config(provider: str) -> dict:
    config = PROVIDERS.get(provider)
    if config is None:
        raise UnsupportedProviderError(f"Unsupported provider: {provider}")
    return config


def _env_prefix(config: dict) -> str:
    # Env assignments only take effect when they're the first word(s) of the
    # shell command, so this must go before `timeout`, not passed as one of
    # its arguments.
    return "".join(f"{key}={value} " for key, value in config.get("env", {}).items())


def start_login(box_id: str, provider: str) -> str:
    config = _provider_config(provider)
    session = _session_name(box_id, provider)

    _ensure_box_running(box_id)

    _run(box_id, f"tmux kill-session -t {session} 2>/dev/null; true")

    _run(
        box_id,
        f'tmux new-session -d -s {session} -x 500 -y 50 '
        f'"{_env_prefix(config)}timeout --foreground {config["abandon_timeout_seconds"]}s '
        f'{config["login_command"]}; echo DONE_$?; sleep 60"',
    )

    for _ in range(URL_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        pane = _run(box_id, f"tmux capture-pane -t {session} -p")
        match = re.search(r"https?://\S+", pane)
        if match:
            return match.group(0)

    raise LoginTimeoutError("Timed out waiting for login URL")


def submit_code(box_id: str, provider: str, code: str) -> str:
    config = _provider_config(provider)
    session = _session_name(box_id, provider)

    _ensure_box_running(box_id)

    _run(box_id, f'tmux send-keys -t {session} "{code}" Enter')

    for _ in range(CODE_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        pane = _run(box_id, f"tmux capture-pane -t {session} -p")
        matches = re.findall(r"DONE_(\d+)", pane)
        if matches:
            exit_code = matches[-1]
            _run(box_id, f"tmux kill-session -t {session} 2>/dev/null; true")

            if exit_code != "0":
                raise LoginFailedError(f"Login process exited with code {exit_code}")

            file_response = ascii_box_service.read_file(box_id, config["credential_path"])
            return file_response.content

    raise LoginTimeoutError("Timed out waiting for login to complete")


def start_device_login(box_id: str, provider: str) -> DeviceLogin:
    """Starts a device-code login (e.g. GitHub) that the user approves on a
    web page, with no code to paste back. Returns the URL and one-time code
    to show them; call await_device_login afterwards to wait for completion.
    """
    config = _provider_config(provider)
    session = _session_name(box_id, provider)

    _ensure_box_running(box_id)

    _run(box_id, f"tmux kill-session -t {session} 2>/dev/null; true")

    _run(
        box_id,
        f'tmux new-session -d -s {session} -x 500 -y 50 '
        f'"{_env_prefix(config)}timeout --foreground {config["abandon_timeout_seconds"]}s '
        f'{config["login_command"]}; echo DONE_$?; sleep 60"',
    )

    dismissed_prompt = False
    for _ in range(DEVICE_CODE_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        pane = _run(box_id, f"tmux capture-pane -t {session} -p")

        code_match = re.search(r"one-time code:\s*(\S+)", pane)
        url_match = re.search(r"https?://\S+", pane)
        if code_match and url_match:
            # Unblocks the "Press Enter to open ... in your browser" prompt
            # so the login command moves on to polling for approval.
            _run(box_id, f"tmux send-keys -t {session} Enter")
            return DeviceLogin(url=url_match.group(0), code=code_match.group(1))

        if not dismissed_prompt and "(Y/n)" in pane:
            _run(box_id, f"tmux send-keys -t {session} Enter")
            dismissed_prompt = True

    raise LoginTimeoutError("Timed out waiting for device login code")


def await_device_login(box_id: str, provider: str) -> str:
    """Waits for a device-code login started with start_device_login to be
    approved, then returns the resulting credential file's content.
    """
    config = _provider_config(provider)
    session = _session_name(box_id, provider)

    _ensure_box_running(box_id)

    for _ in range(DEVICE_COMPLETION_POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECONDS)
        pane = _run(box_id, f"tmux capture-pane -t {session} -p")
        matches = re.findall(r"DONE_(\d+)", pane)
        if matches:
            exit_code = matches[-1]
            _run(box_id, f"tmux kill-session -t {session} 2>/dev/null; true")

            if exit_code != "0":
                raise LoginFailedError(f"Login process exited with code {exit_code}")

            file_response = ascii_box_service.read_file(box_id, config["credential_path"])
            return file_response.content

    raise LoginTimeoutError("Timed out waiting for login to complete")
