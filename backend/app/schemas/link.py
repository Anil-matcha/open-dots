from datetime import datetime

from pydantic import BaseModel


class LinkCodeCreateResponse(BaseModel):
    code: str
    expires_at: datetime
    bot_username: str | None = None


class LinkCodeStatusResponse(BaseModel):
    status: str  # "pending" | "claimed" | "expired"
    user_id: str | None = None
