from datetime import datetime

from pydantic import BaseModel


class TaskCreateRequest(BaseModel):
    user_id: str
    provider: str
    box_id: str
    prompt_text: str
    # Set to reply within an existing conversation instead of starting a new
    # one — the reply continues that task's Claude session.
    parent_task_id: int | None = None


class TaskResponse(BaseModel):
    id: int
    user_id: str
    provider: str
    box_id: str
    prompt_text: str
    status: str
    prompt_id: str | None = None
    session_id: str | None = None
    schedule_id: int | None = None
    scheduled_for: datetime | None = None
    result: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
