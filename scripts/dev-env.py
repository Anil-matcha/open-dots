"""Prepare persistent local secrets and emit shell-safe environment exports."""

import os
from pathlib import Path
import re
import secrets
import shlex
import sys

from cryptography.fernet import Fernet
from dotenv import dotenv_values, set_key


def prepare_environment(path: Path) -> dict[str, str]:
    values = {
        name: os.environ.get(name, value)
        for name, value in dotenv_values(path).items()
        if value is not None
    }
    for name in values:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid environment variable name in {path}: {name}")

    encryption_keys = os.environ.get(
        "TOKEN_ENCRYPTION_KEYS", values.get("TOKEN_ENCRYPTION_KEYS", "")
    )
    if encryption_keys:
        keys = [key.strip() for key in encryption_keys.split(",") if key.strip()]
        try:
            if not keys:
                raise ValueError("No encryption keys provided")
            for key in keys:
                Fernet(key.encode())
        except (ValueError, UnicodeError) as exc:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEYS must contain valid Fernet keys. "
                "Restore the existing key used to encrypt stored credentials."
            ) from exc
    else:
        encryption_keys = Fernet.generate_key().decode()
        set_key(path, "TOKEN_ENCRYPTION_KEYS", encryption_keys)
        print("==> Generated and saved TOKEN_ENCRYPTION_KEYS", file=sys.stderr)
    values["TOKEN_ENCRYPTION_KEYS"] = encryption_keys

    hook_token = os.environ.get("HOOK_TOKEN", values.get("HOOK_TOKEN", ""))
    if not hook_token or hook_token == "your-secret-token-here":
        hook_token = secrets.token_urlsafe(32)
        set_key(path, "HOOK_TOKEN", hook_token)
        print("==> Generated and saved HOOK_TOKEN", file=sys.stderr)
    values["HOOK_TOKEN"] = hook_token
    return values


def main() -> None:
    try:
        values = prepare_environment(Path(sys.argv[1]))
    except (OSError, ValueError) as exc:
        print(f"Cannot prepare development configuration: {exc}", file=sys.stderr)
        sys.exit(1)
    for name, value in values.items():
        print(f"export {name}={shlex.quote(value)}")


if __name__ == "__main__":
    main()
