from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.services.permission_service import check_permission as check_permission_rule

router = APIRouter(
    prefix="/permissions",
    tags=["Permissions"],
)

# Coarse first pass: no real connectors exist yet, so every tool maps to a
# bucket only (no connector/tool-level granularity). Anything not listed
# here defaults to "system" — the most cautious bucket — rather than being
# assumed safe.
TOOL_BUCKETS = {
    "Read": "read",
    "Grep": "read",
    "Glob": "read",
    "WebFetch": "read",
    "WebSearch": "read",
    "Write": "create",
    "Edit": "create",
    "Bash": "system",
}


@router.get("/health")
def health_check():
    """
    Health check endpoint for the permissions router.
    """

    return {"status": "ok"}


@router.post("/check/{user_id}")
async def check_permission(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Answer a Claude Code PermissionRequest hook call for the given user's
    running task. Maps the tool being called to a risk bucket, asks the
    permission engine for a decision, and returns it in the shape Claude
    Code expects.
    """
    if request.headers.get("authorization") != f"Bearer {settings.HOOK_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    tool_name = body.get("tool_name", "")
    bucket = TOOL_BUCKETS.get(tool_name, "system")

    decision = await check_permission_rule(db, user_id, bucket)
    # "ask" has no equivalent at this layer yet (no way to pause and wait
    # for a Telegram/web answer) — treat it as deny until that's built.
    behavior = "allow" if decision == "allow" else "deny"

    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": behavior},
        }
    }
    
    
    
  
   