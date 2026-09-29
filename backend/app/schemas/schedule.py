from datetime import datetime

from pydantic import BaseModel


class ScheduleCreateRequest(BaseModel):
    user_id: str
    provider: str
    box_id: str
    prompt_text: str
    # Standard 5-field crontab, e.g. "0 8 * * *" for 8am daily.
    cron_expression: str
    # IANA name, e.g. "Asia/Kolkata"; the cron expression is read in this zone.
    timezone: str = "UTC"


class ScheduleUpdateRequest(BaseModel):
    provider: str | None = None
    box_id: str | None = None
    prompt_text: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None


class ScheduleResponse(BaseModel):
    id: int
    user_id: str
    provider: str
    box_id: str
    prompt_text: str
    cron_expression: str
    timezone: str
    is_active: bool
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int
    paused_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
