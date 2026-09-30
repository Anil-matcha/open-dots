"""Authenticated computer lifecycle and provider action endpoints."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.action_gateway import (
    ActionGatewayError,
    ActionInvocation,
    ActionPolicyError,
    action_gateway,
)
from app.services.computer_provider import ComputerProviderError, computer_provider
from app.services.storage_service import storage_service
from app.services import computer_actions as _computer_actions  # noqa: F401 - registers actions


router = APIRouter(prefix="/api/v1/computers", tags=["computers"])


class ComputerActionRequest(BaseModel):
    action: Literal[
        "browser_navigate",
        "terminal_execute",
        "files_list",
        "send_input",
        "cleanup",
    ]
    arguments: Dict[str, Any] = Field(default_factory=dict)


def _ensure_bot(bot_id: str) -> None:
    if not any(bot.get("id") == bot_id for bot in storage_service.get_bots()):
        raise HTTPException(status_code=404, detail="Bot not found")


def _preview(action: str, bot_id: str, arguments: Dict[str, Any]) -> str:
    if action == "browser_navigate":
        return f"Navigate the computer for {bot_id} to {arguments.get('url') or '[missing URL]'}"
    if action == "terminal_execute":
        return f"Run a terminal command on the computer for {bot_id}"
    if action == "files_list":
        return f"List computer files for {bot_id} at {arguments.get('path') or '/workspace'}"
    if action == "send_input":
        return f"Send input to the computer for {bot_id}"
    if action == "cleanup":
        return f"Remove the computer assigned to {bot_id}"
    return f"Run computer action {action} for {bot_id}"


async def _run_action(
    bot_id: str,
    action: str,
    arguments: Optional[Dict[str, Any]] = None,
):
    _ensure_bot(bot_id)
    status = computer_provider.describe(bot_id)
    action_arguments = dict(arguments or {})
    # The URL path is the ownership boundary; callers cannot redirect an
    # action to another bot by smuggling ids inside its argument object.
    action_arguments.pop("bot_id", None)
    action_arguments.pop("computer_id", None)
    action_arguments.update({"bot_id": bot_id, "computer_id": status.computer_id})
    call = ActionInvocation(
        name=f"computer.{action}",
        arguments=action_arguments,
        target={"bot_id": bot_id, "computer_id": status.computer_id},
        preview=_preview(action, bot_id, action_arguments),
    )
    try:
        request, approval = action_gateway.open(
            thread_id=f"computer:{bot_id}",
            bot_id=bot_id,
            call=call,
        )
    except ActionPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if approval:
        return JSONResponse(
            status_code=202,
            content={
                "status": "pending_approval",
                "request": request.model_dump(),
                "approval": approval,
            },
        )

    try:
        result = await action_gateway.execute(request)
    except ActionGatewayError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.status != "completed":
        raise HTTPException(status_code=409, detail=result.error or "Computer action failed.")
    return {
        "status": "completed",
        "request": request.model_dump(),
        "result": result.result or {},
    }

@router.get("/{bot_id}")
async def computer_status(bot_id: str):
    _ensure_bot(bot_id)
    reconcile = getattr(computer_provider, "reconcile", None)
    status = await reconcile(bot_id) if reconcile else computer_provider.describe(bot_id)
    return {
        "status": status.to_dict(),
        "created": status.generation > 0,
    }


@router.post("/{bot_id}/create")
async def create_computer(bot_id: str):
    return await _run_action(bot_id, "create")


@router.post("/{bot_id}/start")
async def start_computer(bot_id: str):
    return await _run_action(bot_id, "start")


@router.post("/{bot_id}/pause")
async def pause_computer(bot_id: str):
    return await _run_action(bot_id, "pause")


@router.post("/{bot_id}/stop")
async def stop_computer(bot_id: str):
    return await _run_action(bot_id, "stop")


@router.post("/{bot_id}/reset")
async def reset_computer(bot_id: str):
    return await _run_action(bot_id, "reset")


@router.post("/{bot_id}/health")
async def health_computer(bot_id: str):
    return await _run_action(bot_id, "health")


@router.post("/{bot_id}/screenshot")
async def screenshot_computer(bot_id: str):
    return await _run_action(bot_id, "screenshot")


@router.post("/{bot_id}/actions")
async def run_computer_action(bot_id: str, action: ComputerActionRequest):
    """Open a provider action; writes return 202 until approval is resolved."""

    return await _run_action(bot_id, action.action, action.arguments)


@router.post("/{bot_id}/actions/{request_id}/execute")
async def execute_approved_computer_action(bot_id: str, request_id: str):
    _ensure_bot(bot_id)
    request = action_gateway.get_pending_request(request_id)
    if request is None or request.bot_id != bot_id or request.tool != "computer":
        raise HTTPException(status_code=404, detail="Computer action request not found")

    decision = await action_gateway.wait_for_decision(request)
    if decision != "allow":
        return {"status": decision, "request": request.model_dump()}
    try:
        result = await action_gateway.execute(request)
    except ActionGatewayError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.status != "completed":
        raise HTTPException(status_code=409, detail=result.error or "Computer action failed.")
    return {
        "status": "completed",
        "request": request.model_dump(),
        "result": result.result or {},
    }
