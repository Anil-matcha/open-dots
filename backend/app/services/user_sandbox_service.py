from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_sandbox import UserSandbox


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    box_id: str,
    state: str | None,
    machine_type: str | None,
    ttl_seconds: int,
) -> UserSandbox:
    record = UserSandbox(
        user_id=user_id,
        box_id=box_id,
        state=state,
        machine_type=machine_type,
        ttl_seconds=ttl_seconds,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_by_box_id(db: AsyncSession, box_id: str) -> UserSandbox | None:
    result = await db.execute(
        select(UserSandbox).where(UserSandbox.box_id == box_id)
    )
    return result.scalar_one_or_none()


async def get_active_by_user_id(db: AsyncSession, user_id: str) -> UserSandbox | None:
    result = await db.execute(
        select(UserSandbox)
        .where(UserSandbox.user_id == user_id, UserSandbox.is_active.is_(True))
        .order_by(UserSandbox.created_at.desc())
    )
    return result.scalars().first()


async def update_state(
    db: AsyncSession, box_id: str, *, state: str | None
) -> UserSandbox | None:
    record = await get_by_box_id(db, box_id)
    if record is None:
        return None

    record.state = state
    await db.commit()
    await db.refresh(record)
    return record


async def deactivate(db: AsyncSession, box_id: str) -> UserSandbox | None:
    record = await get_by_box_id(db, box_id)
    if record is None:
        return None

    record.is_active = False
    await db.commit()
    await db.refresh(record)
    return record
