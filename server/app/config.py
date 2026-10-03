import os
from pathlib import Path

class Settings:
    MODEL_API_KEY: str = os.getenv("MODEL_API_KEY", "")
    MODEL_API_BASE_URL: str = os.getenv("MODEL_API_BASE_URL", "").rstrip("/")
    COMPOSIO_API_KEY: str = os.getenv("COMPOSIO_API_KEY", "")
    YDC_API_KEY: str = os.getenv("YDC_API_KEY", "").strip()
    COHESIVITY_MANAGEMENT_KEY: str = os.getenv("COHESIVITY_MANAGEMENT_KEY", "").strip()
    COHESIVITY_TENANT_ID: str = os.getenv("COHESIVITY_TENANT_ID", "").strip()
    DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gpt-5-mini")
    DATA_DIR: Path = Path(
        os.getenv("DATA_DIR", str(Path.home() / ".open-dots"))
    ).expanduser().resolve()
    WORKSPACE_ROOT: Path = Path(
        os.getenv("WORKSPACE_ROOT", str(Path(__file__).resolve().parents[2]))
    ).expanduser().resolve()
    WORKSPACE_MAX_FILE_BYTES: int = int(os.getenv("WORKSPACE_MAX_FILE_BYTES", "131072"))
    APPROVAL_TIMEOUT_SECONDS: int = int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "120"))
    AUTH_SESSION_MAX_AGE: int = int(os.getenv("AUTH_SESSION_MAX_AGE", "86400"))
    AUTH_COOKIE_SECURE: bool = os.getenv("AUTH_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
    # ``fake`` is retained for deterministic tests. Real deployments should
    # select ``docker`` or ``remote`` explicitly.
    COMPUTER_PROVIDER: str = os.getenv("COMPUTER_PROVIDER", "fake").strip().lower()
    COMPUTER_DOCKER_IMAGE: str = os.getenv(
        "COMPUTER_DOCKER_IMAGE", "open-dots-computer:1.62.1"
    ).strip()
    COMPUTER_DOCKER_BINARY: str = os.getenv("COMPUTER_DOCKER_BINARY", "docker").strip()
    COMPUTER_DOCKER_WORKSPACE_ROOT: Path = Path(
        os.getenv("COMPUTER_DOCKER_WORKSPACE_ROOT", str(DATA_DIR / "computers"))
    ).expanduser().resolve()
    COMPUTER_DOCKER_CPU_LIMIT: str = os.getenv("COMPUTER_DOCKER_CPU_LIMIT", "2.0").strip()
    COMPUTER_DOCKER_MEMORY_LIMIT: str = os.getenv("COMPUTER_DOCKER_MEMORY_LIMIT", "2g").strip()
    COMPUTER_DOCKER_PIDS_LIMIT: int = int(os.getenv("COMPUTER_DOCKER_PIDS_LIMIT", "512"))
    COMPUTER_DOCKER_START_TIMEOUT: float = float(
        os.getenv("COMPUTER_DOCKER_START_TIMEOUT", "20")
    )
    COMPUTER_DOCKER_COMMAND_TIMEOUT: float = float(
        os.getenv("COMPUTER_DOCKER_COMMAND_TIMEOUT", "30")
    )
    COMPUTER_DOCKER_RUNTIME_PORT: int = int(os.getenv("COMPUTER_DOCKER_RUNTIME_PORT", "3000"))
    COMPUTER_DOCKER_SECCOMP_PROFILE: Path = Path(
        os.getenv("COMPUTER_DOCKER_SECCOMP_PROFILE", "/nonexistent/open-dots-seccomp.json")
    ).expanduser().resolve()
    COMPUTER_REMOTE_BASE_URL: str = os.getenv("COMPUTER_REMOTE_BASE_URL", "").rstrip("/")
    COMPUTER_REMOTE_API_KEY: str = os.getenv("COMPUTER_REMOTE_API_KEY", "").strip()
    COMPUTER_REMOTE_AUTH_HEADER: str = os.getenv(
        "COMPUTER_REMOTE_AUTH_HEADER", "Authorization"
    ).strip()
    COMPUTER_REMOTE_AUTH_SCHEME: str = os.getenv(
        "COMPUTER_REMOTE_AUTH_SCHEME", "Bearer"
    ).strip()
    COMPUTER_REMOTE_TIMEOUT: float = float(os.getenv("COMPUTER_REMOTE_TIMEOUT", "30"))
    COMPUTER_REMOTE_START_TIMEOUT: float = float(
        os.getenv("COMPUTER_REMOTE_START_TIMEOUT", "60")
    )
    COMPUTER_REMOTE_WIDTH: int = int(os.getenv("COMPUTER_REMOTE_WIDTH", "1280"))
    COMPUTER_REMOTE_HEIGHT: int = int(os.getenv("COMPUTER_REMOTE_HEIGHT", "720"))
    COMPUTER_REMOTE_FPS: int = int(os.getenv("COMPUTER_REMOTE_FPS", "10"))
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000",
        ).split(",")
        if origin.strip()
    ]
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.COMPUTER_DOCKER_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

settings = Settings()
