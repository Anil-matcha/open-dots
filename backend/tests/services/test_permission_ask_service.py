from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.permission_ask import PermissionAsk
from app.db.models.permission_rule import PermissionRule
from app.db.models.task import Tasks
from app.services.permission_ask_service import answer_ask, create_ask, poll_for_answer
from app.services.permission_service import check_permission


async def _add_task(db: AsyncSession, user_id: str, status: str = "running") -> Tasks:
    task = Tasks(
        user_id=user_id,
        provider="claude",
        box_id="box-1",
        prompt_text="do something",
        status=status,
        session_id="session-1",
    )
    db.add(task)
    await db.flush()
    return task


async def test_create_ask_marks_task_waiting_approval(
    db_session: AsyncSession, user_id: str
) -> None:
    task = await _add_task(db_session, user_id)

    ask = await create_ask(db_session, user_id, bucket="create", task_id=task.id)

    assert ask.status == "pending"
    assert ask.decision is None
    await db_session.refresh(task)
    assert task.status == "waiting_approval"


async def test_answer_ask_allow_updates_ask_and_resumes_task(
    db_session: AsyncSession, user_id: str
) -> None:
    task = await _add_task(db_session, user_id)
    ask = await create_ask(db_session, user_id, bucket="create", task_id=task.id)

    answered = await answer_ask(db_session, ask.id, decision="allow", always=False)

    assert answered.status == "answered"
    assert answered.decision == "allow"
    assert answered.answered_at is not None
    await db_session.refresh(task)
    assert task.status == "running"


async def test_answer_ask_always_writes_permission_rule(
    db_session: AsyncSession, user_id: str
) -> None:
    # tool/connector are set on the ask (for display in the notification),
    # but the hook only ever checks by bucket (no connector concept exists
    # yet) — so the written rule must be bucket-level, matching that.
    task = await _add_task(db_session, user_id)
    ask = await create_ask(
        db_session, user_id, bucket="create", task_id=task.id, tool="Write"
    )

    await answer_ask(db_session, ask.id, decision="allow", always=True)

    result = await db_session.execute(
        select(PermissionRule).where(
            PermissionRule.user_id == user_id,
            PermissionRule.bucket == "create",
            PermissionRule.connector.is_(None),
            PermissionRule.tool.is_(None),
        )
    )
    rule = result.scalar_one()
    assert rule.decision == "allow"

    # The regression this guards against: a later bucket-only lookup (what
    # the hook actually does) must now find this rule.
    decision = await check_permission(db_session, user_id, bucket="create")
    assert decision == "allow"


async def test_answer_ask_without_always_writes_no_permission_rule(
    db_session: AsyncSession, user_id: str
) -> None:
    task = await _add_task(db_session, user_id)
    ask = await create_ask(db_session, user_id, bucket="create", task_id=task.id)

    await answer_ask(db_session, ask.id, decision="allow", always=False)

    result = await db_session.execute(
        select(PermissionRule).where(PermissionRule.user_id == user_id)
    )
    assert result.scalar_one_or_none() is None


async def test_answer_ask_is_idempotent(db_session: AsyncSession, user_id: str) -> None:
    task = await _add_task(db_session, user_id)
    ask = await create_ask(db_session, user_id, bucket="create", task_id=task.id)

    await answer_ask(db_session, ask.id, decision="allow", always=False)
    # A second answer (e.g. a double-tapped button) must not flip the
    # decision or write a second rule.
    second = await answer_ask(db_session, ask.id, decision="deny", always=True)

    assert second.decision == "allow"
    result = await db_session.execute(
        select(PermissionRule).where(PermissionRule.user_id == user_id)
    )
    assert result.scalar_one_or_none() is None


async def test_poll_for_answer_returns_once_answered(
    db_session: AsyncSession, user_id: str
) -> None:
    task = await _add_task(db_session, user_id)
    ask = await create_ask(db_session, user_id, bucket="create", task_id=task.id)
    await answer_ask(db_session, ask.id, decision="deny", always=False)

    decision = await poll_for_answer(
        db_session, ask.id, timeout_seconds=1, interval_seconds=0.1
    )

    assert decision == "deny"


async def test_poll_for_answer_times_out_to_deny_and_expires_ask(
    db_session: AsyncSession, user_id: str
) -> None:
    task = await _add_task(db_session, user_id)
    ask = await create_ask(db_session, user_id, bucket="create", task_id=task.id)

    # No answer_ask call — this ask is left pending on purpose, so the short
    # timeout below is what resolves it instead of a human.
    decision = await poll_for_answer(
        db_session, ask.id, timeout_seconds=0.2, interval_seconds=0.1
    )

    assert decision == "deny"
    result = await db_session.execute(
        select(PermissionAsk).where(PermissionAsk.id == ask.id)
    )
    assert result.scalar_one().status == "expired"

    # An expired ask must not leave its task stuck in waiting_approval
    # forever — nothing would ever move it out of that state otherwise.
    await db_session.refresh(task)
    assert task.status == "running"
