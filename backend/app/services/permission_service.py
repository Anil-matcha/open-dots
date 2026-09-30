from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.permission_rule import PermissionRule

Decision = Literal["allow", "deny", "ask"]


async def _query_db(db: AsyncSession, query) -> Decision | None:
    query = query.order_by(PermissionRule.created_at.desc()).limit(1)
    query_results = await db.execute(query)
    result = query_results.scalars().first()

    if result is None:
        return None

    return cast(Decision, result.decision)


async def check_permission(
    db: AsyncSession,
    user_id: str,
    bucket: str,
    connector: str | None = None,
    tool: str | None = None,
) -> Decision:
    
    """ Function to check the permisson for a user to access a specific bucket, connector, and tool. 
    The function checks for the most specific permission rule first (tool-level), then connector-level, and finally bucket-level. If no rule is found, it defaults to "ask". 
    
    Args:
        db (AsyncSession): The database session to use for the query.
        user_id (str): The ID of the user for whom the permission is being checked.
        bucket (str): The name of the bucket for which the permission is being checked.
        connector (str | None, optional): The name of the connector for which the permission is being checked. Defaults to None.
        tool (str | None, optional): The name of the tool for which the permission is being checked. Defaults to None.
        
    Returns:
        Decision: The decision for the permission check, which can be "allow", "deny", or "ask". If no rule is found, it defaults to "ask".
    
    """
    
    # Most specific first: tool-level rule (only meaningful when a connector
    # is also given, since a tool always belongs to a connector).
    if connector is not None and tool is not None:
        query = select(PermissionRule).where(
            PermissionRule.user_id == user_id,
            PermissionRule.bucket == bucket,
            PermissionRule.connector == connector,
            PermissionRule.tool == tool,
        )
        decision = await _query_db(db, query)
        if decision is not None:
            return decision

    # Connector-level rule (no specific tool).
    if connector is not None:
        query = select(PermissionRule).where(
            PermissionRule.user_id == user_id,
            PermissionRule.bucket == bucket,
            PermissionRule.connector == connector,
            PermissionRule.tool.is_(None),
        )
        decision = await _query_db(db, query)
        if decision is not None:
            return decision

    # Bucket-level default (no connector, no tool).
    query = select(PermissionRule).where(
        PermissionRule.user_id == user_id,
        PermissionRule.bucket == bucket,
        PermissionRule.connector.is_(None),
        PermissionRule.tool.is_(None),
    )
    decision = await _query_db(db, query)
    if decision is not None:
        return decision

    # No rule means ask, never means proceed on a guess.
    return "ask"