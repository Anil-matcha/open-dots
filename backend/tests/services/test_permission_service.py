from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.permission_rule import PermissionRule
from app.services.permission_service import check_permission


async def _add_rule(
    db: AsyncSession,
    user_id: str,
    bucket: str,
    decision: str,
    connector: str | None = None,
    tool: str | None = None,
    created_at: datetime | None = None,
) -> None:
    rule = PermissionRule(
        user_id=user_id,
        bucket=bucket,
        connector=connector,
        tool=tool,
        decision=decision,
    )
    if created_at is not None:
        rule.created_at = created_at
    db.add(rule)
    await db.flush()


async def test_no_rule_means_ask(db_session: AsyncSession, user_id: str) -> None:
    decision = await check_permission(db_session, user_id, bucket="publish")
    assert decision == "ask"


async def test_bucket_level_rule_applies(db_session: AsyncSession, user_id: str) -> None:
    await _add_rule(db_session, user_id, bucket="publish", decision="allow")

    decision = await check_permission(db_session, user_id, bucket="publish")
    assert decision == "allow"


async def test_connector_level_rule_overrides_bucket_default(
    db_session: AsyncSession, user_id: str
) -> None:
    await _add_rule(db_session, user_id, bucket="publish", decision="deny")
    await _add_rule(
        db_session, user_id, bucket="publish", decision="allow", connector="medium"
    )

    decision = await check_permission(
        db_session, user_id, bucket="publish", connector="medium"
    )
    assert decision == "allow"


async def test_tool_level_rule_overrides_connector_level(
    db_session: AsyncSession, user_id: str
) -> None:
    await _add_rule(
        db_session, user_id, bucket="publish", decision="allow", connector="medium"
    )
    await _add_rule(
        db_session,
        user_id,
        bucket="publish",
        decision="deny",
        connector="medium",
        tool="medium.delete",
    )

    # A different tool under the same connector still gets the connector-level rule.
    decision = await check_permission(
        db_session, user_id, bucket="publish", connector="medium", tool="medium.publish"
    )
    assert decision == "allow"

    # The tool with its own explicit rule gets that rule instead.
    decision = await check_permission(
        db_session, user_id, bucket="publish", connector="medium", tool="medium.delete"
    )
    assert decision == "deny"


async def test_rule_scoped_to_other_user_is_ignored(
    db_session: AsyncSession, user_id: str, other_user_id: str
) -> None:
    await _add_rule(db_session, other_user_id, bucket="publish", decision="allow")

    decision = await check_permission(db_session, user_id, bucket="publish")
    assert decision == "ask"


async def test_bucket_level_deny_is_returned_directly(
    db_session: AsyncSession, user_id: str
) -> None:
    await _add_rule(db_session, user_id, bucket="delete", decision="deny")

    decision = await check_permission(db_session, user_id, bucket="delete")
    assert decision == "deny"


async def test_most_recent_rule_wins_for_the_same_key(
    db_session: AsyncSession, user_id: str
) -> None:
    now = datetime.now(timezone.utc)
    await _add_rule(
        db_session,
        user_id,
        bucket="publish",
        decision="allow",
        connector="medium",
        created_at=now - timedelta(minutes=5),
    )
    await _add_rule(
        db_session,
        user_id,
        bucket="publish",
        decision="deny",
        connector="medium",
        created_at=now,
    )

    decision = await check_permission(
        db_session, user_id, bucket="publish", connector="medium"
    )
    assert decision == "deny"
