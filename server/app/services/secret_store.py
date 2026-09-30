"""At-rest encryption for provider credentials."""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretStoreError(RuntimeError):
    """Raised when the local encryption key or ciphertext is unusable."""


class SecretStore:
    """Use an explicit environment key or a mode-0600 local key file."""

    def __init__(self, data_dir: Path):
        self.key_path = data_dir / ".encryption.key"
        configured_key = os.getenv("APP_ENCRYPTION_KEY", "").strip()
        if configured_key:
            key = configured_key.encode("utf-8")
        elif self.key_path.exists():
            key = self.key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            # Create the key file with 0600 from the start: write_bytes()
            # would leave a brief world-readable window before chmod().
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "wb") as key_file:
                    key_file.write(key + b"\n")
            except Exception:
                os.close(fd)
                raise

        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise SecretStoreError(
                "APP_ENCRYPTION_KEY must be a valid Fernet key."
            ) from exc
        if self.key_path.exists():
            os.chmod(self.key_path, 0o600)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise SecretStoreError("Stored credential could not be decrypted.") from exc
