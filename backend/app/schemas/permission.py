from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PermissionAskResponse(BaseModel):
    id: int
    task_id: int
    user_id: str
    bucket: str
    connector: str | None = None
    tool: str | None = None
    status: str
    decision: str | None = None
    created_at: datetime
    answered_at: datetime | None = None

    model_config = {"from_attributes": True}


class AnswerAskRequest(BaseModel):
    decision: Literal["allow", "deny"]
    always: bool = False
