from datetime import UTC, datetime

import httpx
import pytest
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.routers.schedule import router
from app.services.schedule_service import InvalidScheduleError, compute_next_run
from app.telegram_bot import _parse_schedule_args


@pytest.mark.parametrize(
    "cron, after, expected",
    [
        ("0 8 * * 0", "2026-10-04T00:00:00", "2026-10-04T08:00:00"),
        ("0 8 * * 1", "2026-10-05T00:00:00", "2026-10-05T08:00:00"),
        ("0 8 * * 1-5", "2026-10-05T00:00:00", "2026-10-05T08:00:00"),
        ("0 8 * * 1-5", "2026-10-10T00:00:00", "2026-10-12T08:00:00"),
        ("0 8 * * 0,6", "2026-10-10T00:00:00", "2026-10-10T08:00:00"),
        ("0 8 * * 0-6", "2026-10-05T00:00:00", "2026-10-05T08:00:00"),
        ("0 8 * * 1-5/2", "2026-10-05T00:00:00", "2026-10-05T08:00:00"),
        ("0 8 * * */2", "2026-10-05T00:00:00", "2026-10-06T08:00:00"),
        ("0 8 * * sun", "2026-10-04T00:00:00", "2026-10-04T08:00:00"),
        ("0 8 * * *", "2026-10-04T00:00:00", "2026-10-04T08:00:00"),
        ("0 8 * * 0", "2026-10-04T08:00:00", "2026-10-11T08:00:00"),
        ("0 9 13 * fri", "2026-01-01T00:00:00", "2026-01-02T09:00:00"),
        ("0 9 13 * fri", "2026-01-03T00:00:00", "2026-01-09T09:00:00"),
        ("0 9 13 * fri", "2026-01-10T00:00:00", "2026-01-13T09:00:00"),
        ("0 9 13 * *", "2026-01-01T00:00:00", "2026-01-13T09:00:00"),
        ("0 9 * * fri", "2026-01-01T00:00:00", "2026-01-02T09:00:00"),
        ("0 9 */2 * fri", "2026-01-01T00:00:00", "2026-01-09T09:00:00"),
        ("0 9 13 * */2", "2026-01-01T00:00:00", "2026-01-13T09:00:00"),
    ],
)
def test_standard_crontab_next_run(cron: str, after: str, expected: str) -> None:
    result = compute_next_run(cron, "UTC", datetime.fromisoformat(after).replace(tzinfo=UTC))
    assert result == datetime.fromisoformat(expected).replace(tzinfo=UTC)


def test_weekday_translation_preserves_timezone() -> None:
    after = datetime(2026, 10, 4, tzinfo=UTC)
    assert compute_next_run("0 8 * * 0", "Asia/Kolkata", after) == datetime(
        2026, 10, 4, 2, 30, tzinfo=UTC
    )


@pytest.mark.parametrize("name, date", [("sun", 4), ("mon", 5), ("sat", 10)])
def test_telegram_weekly_presets(name: str, date: int) -> None:
    expression, prompt = _parse_schedule_args(["weekly", name, "08:00", "report"])
    after = datetime(2026, 10, date, tzinfo=UTC)
    assert prompt == "report"
    assert compute_next_run(expression, "UTC", after) == after.replace(hour=8)


@pytest.mark.parametrize("cron", ["0 8 * * 8", "0 8 * * 5-1", "0 8 * * */0", "0 25 * * *", "not cron"])
def test_invalid_crontab_still_rejected(cron: str) -> None:
    with pytest.raises(InvalidScheduleError):
        compute_next_run(cron, "UTC", datetime(2026, 10, 4, tzinfo=UTC))


@pytest.mark.parametrize(
    "expression, expected_weekday", [("0 8 * * 0", 6), ("0 8 * * 1", 0), ("0 8 * * sun", 6)]
)
async def test_schedule_route_persists_requested_weekday(
    db_session: AsyncSession, user_id: str, expression: str, expected_weekday: int
) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://owned") as client:
        response = await client.post("/api/v1/schedules", json={
            "user_id": user_id, "provider": "claude", "box_id": "owned-box",
            "prompt_text": "weekly report", "cron_expression": expression, "timezone": "UTC",
        })
    assert response.status_code == 200
    body = response.json()
    assert body["cron_expression"] == expression
    next_run = datetime.fromisoformat(body["next_run_at"])
    assert next_run.weekday() == expected_weekday
    assert next_run.hour == 8
    assert next_run > datetime.now(UTC)


async def test_schedule_route_persists_first_of_restricted_days(
    db_session: AsyncSession, user_id: str
) -> None:
    now = datetime.now(UTC)
    expected = min(
        CronTrigger.from_crontab("0 9 13 * *", timezone=UTC).get_next_fire_time(None, now),
        CronTrigger.from_crontab("0 9 * * fri", timezone=UTC).get_next_fire_time(None, now),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://owned") as client:
        response = await client.post("/api/v1/schedules", json={
            "user_id": user_id, "provider": "claude", "box_id": "owned-box",
            "prompt_text": "Friday or thirteenth report", "cron_expression": "0 9 13 * fri", "timezone": "UTC",
        })
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["next_run_at"]) == expected
