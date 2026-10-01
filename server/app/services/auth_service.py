"""Authentication primitives for the single-owner local deployment."""

import hashlib
import os
import secrets
from time import monotonic
from pathlib import Path
from typing import Dict, Optional

from fastapi import Request, Response

from app.config import settings


LOCAL_USER_ID = "local-user"
LOCAL_USERNAME = "local"
SESSION_COOKIE = "open_dots_session"


class AuthService:
    """Exchange an explicit owner credential for a revocable browser session.

    Peer addresses are not identity: container gateways and reverse proxies can
    make untrusted clients appear to originate from loopback. Session tokens are
    separate random values, stored as hashes in memory and invalidated on restart.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = (data_dir or settings.DATA_DIR).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.token_path = self.data_dir / ".auth-token"
        self.configured_token = os.getenv("APP_AUTH_TOKEN", "").strip()
        self.token = self.configured_token or self._load_or_create_token()
        self._sessions: Dict[str, float] = {}

    @property
    def user(self) -> Dict[str, str]:
        return {"id": LOCAL_USER_ID, "username": LOCAL_USERNAME, "role": "owner"}

    def _load_or_create_token(self) -> str:
        if self.token_path.exists():
            existing = self.token_path.read_text(encoding="utf-8").strip()
            if existing:
                os.chmod(self.token_path, 0o600)
                return existing

        token = secrets.token_urlsafe(32)
        # Create the file with 0600 from the start: write_text() would leave a
        # brief world-readable window before chmod().
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as token_file:
                token_file.write(token + "\n")
        except Exception:
            os.close(fd)
            raise
        return token

    def authenticate_token(self, token: Optional[str]) -> bool:
        return bool(token) and secrets.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))

    def authenticate_session(self, token: Optional[str]) -> bool:
        if not token or len(token) > 128:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires = self._sessions.get(digest)
        if expires is None:
            return False
        if monotonic() >= expires:
            self._sessions.pop(digest, None)
            return False
        return True

    def authenticate_request(self, request: Request) -> Optional[Dict[str, str]]:
        authorization = request.headers.get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        if scheme.lower() == "bearer" and self.authenticate_token(bearer.strip()):
            return self.user

        if self.authenticate_session(request.cookies.get(SESSION_COOKIE)):
            return self.user
        return None

    def can_bootstrap(self, request: Request) -> bool:
        # Retained for the status API's bootstrap_available field.
        return False

    def set_session_cookie(self, response: Response, previous_token: Optional[str] = None, *, secure: bool = False) -> None:
        self.revoke_session(previous_token)
        now = monotonic()
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
        while len(self._sessions) >= 128:
            self._sessions.pop(next(iter(self._sessions)))
        session_token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(session_token.encode("ascii")).hexdigest()
        self._sessions[digest] = now + settings.AUTH_SESSION_MAX_AGE
        response.set_cookie(
            SESSION_COOKIE,
            session_token,
            max_age=settings.AUTH_SESSION_MAX_AGE,
            httponly=True,
            secure=settings.AUTH_COOKIE_SECURE or secure,
            samesite="lax",
        )

    def revoke_session(self, token: Optional[str]) -> None:
        if token:
            self._sessions.pop(hashlib.sha256(token.encode("utf-8")).hexdigest(), None)

    @staticmethod
    def clear_session_cookie(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")


auth_service = AuthService()
