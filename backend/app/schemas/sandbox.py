from datetime import datetime

from pydantic import BaseModel, Field


class SandboxCreateRequest(BaseModel):
    user_id: str
    ttl_seconds: int = Field(
        default=1800,
        ge=300,
        le=7200,
    )


class SandboxResponse(BaseModel):
    box_id: str
    state: str | None = None
    machine_type: str | None = None
    user_id: str | None = None
    ttl_seconds: int | None = None
    expires_at: datetime | None = None
    is_active: bool | None = None


class AuthLoginStartResponse(BaseModel):
    login_url: str


class AuthLoginSubmitRequest(BaseModel):
    code: str


class AuthLoginSubmitResponse(BaseModel):
    status: str


class AuthStatusResponse(BaseModel):
    connected: bool


class DeviceLoginStartResponse(BaseModel):
    url: str
    code: str
