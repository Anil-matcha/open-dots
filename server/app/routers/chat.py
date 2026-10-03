import json
import uuid
import asyncio
from datetime import datetime
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
from typing import List, Optional

from app.schemas.contracts import TurnRequest, Message
from app.services.storage_service import storage_service
from app.services.provider_service import provider_service
from app.services.action_gateway import (
    ActionGatewayError,
    ActionPolicyError,
    action_gateway,
)
from app.services.connector_actions import ConnectorCommandError, parse_connector_command
from app.services.search_actions import SearchCommandError, parse_search_command
from app.services.cohesivity_actions import BackendCommandError, parse_backend_command
from app.services.workspace_service import (
    WorkspaceToolError,
    parse_workspace_command,
)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

@router.get("/history/{thread_id}", response_model=List[Message])
async def get_history(thread_id: str):
    return storage_service.get_messages(thread_id=thread_id)

@router.post("/send")
async def send_message(req: TurnRequest):
    # Store user message
    user_msg = {
        "id": f"msg-{uuid.uuid4().hex}",
        "thread_id": req.thread_id,
        "bot_id": req.bot_id,
        "sender": "user",
        "text": req.user_text,
        "image_url": req.image_url,
        "created_at": datetime.now().isoformat(),
        "model": req.model or next(
            (bot.get("model") for bot in storage_service.get_bots() if bot.get("id") == req.bot_id),
            storage_service.get_settings().get("default_model", "gpt-5-mini"),
        ),
        "item_type": "user_text"
    }

    storage_service.add_message(user_msg)
    return {"status": "ok", "message": user_msg}

@router.get("/stream/{thread_id}")
async def stream_turn(thread_id: str, model: Optional[str] = Query(None)):
    """
    SSE stream endpoint broadcasting real-time tokens & tool events for a given thread.
    """
    history = storage_service.get_messages(thread_id=thread_id)
    bots = storage_service.get_bots()
    current_bot = next((b for b in bots if b["id"] == thread_id), None)
    
    raw_prompt = current_bot["system_prompt"] if current_bot else "You are a helpful AI assistant."
    current_time_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    system_prompt = f"Current Date & Time: {current_time_str}.\n\n{raw_prompt}"
    selected_model = model or (current_bot["model"] if current_bot else "gpt-5-mini")

    formatted_history = []
    for m in history:
        if m["sender"] in ["user", "bot"]:
            formatted_history.append({
                "role": "user" if m["sender"] == "user" else "assistant",
                "content": m.get("text", ""),
                "image_url": m.get("image_url")
            })


    async def event_generator():
        bot_msg_id = f"msg-{uuid.uuid4().hex}"
        accumulated_text = ""
        tool_context = ""

        # Emit turn started
        yield {
            "event": "message",
            "data": json.dumps({"type": "turn.started", "botMsgId": bot_msg_id, "model": selected_model})
        }

        last_user_text = formatted_history[-1]["content"] if formatted_history else ""
        try:
            action_call = parse_workspace_command(last_user_text)
            if action_call is None:
                action_call = parse_connector_command(last_user_text)
            if action_call is None:
                action_call = parse_search_command(last_user_text)
            if action_call is None:
                action_call = parse_backend_command(last_user_text)
        except (WorkspaceToolError, ConnectorCommandError, SearchCommandError, BackendCommandError) as exc:
            action_call = None
            lowered_text = last_user_text.lower()
            if lowered_text.startswith("/connector"):
                command_tool = "connector"
            elif lowered_text.startswith("/search"):
                command_tool = "search"
            elif lowered_text.startswith("/backend"):
                command_tool = "backend"
            else:
                command_tool = "workspace"
            tool_context = f"A {command_tool} request was rejected before execution: {exc}"
            yield {
                "event": "message",
                "data": json.dumps({
                    "type": "tool.failed",
                    "tool": command_tool,
                    "error": str(exc),
                }),
            }

        if action_call:
            try:
                action_request, approval = action_gateway.open(
                    thread_id,
                    thread_id,
                    action_call,
                )
            except ActionPolicyError as exc:
                tool_context = f"Action rejected by policy: {exc}"
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "tool.failed",
                        "tool": action_call.name,
                        "requestId": exc.request_id,
                        "error": str(exc),
                    }),
                }
            else:
                if approval:
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "request.opened",
                            "requestType": "permission",
                            "requestId": action_request.request_id,
                            "tool": approval["tool"],
                            "summary": approval["summary"],
                            "arguments": approval["arguments"],
                            "action": action_request.model_dump(),
                        }),
                    }

                decision = await action_gateway.wait_for_decision(action_request)
                action_name = f"{action_request.tool}.{action_request.action}"
                if decision == "allow":
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "tool.started",
                            "tool": action_name,
                            "requestId": action_request.request_id,
                            "action": action_request.model_dump(),
                        }),
                    }
                    try:
                        action_result = await action_gateway.execute(action_request)
                    except ActionGatewayError as exc:
                        tool_context = f"Action could not execute ({action_name}): {exc}"
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "type": "tool.failed",
                                "tool": action_name,
                                "requestId": action_request.request_id,
                                "error": str(exc),
                            }),
                        }
                    else:
                        if action_result.status == "completed":
                            result = action_result.result or {}
                            tool_context = f"Action result ({action_name}): {json.dumps(result)}"
                            yield {
                                "event": "message",
                                "data": json.dumps({
                                    "type": "tool.completed",
                                    "tool": action_name,
                                    "requestId": action_request.request_id,
                                    "result": result,
                                }),
                            }
                        else:
                            error = action_result.error or "The action failed."
                            tool_context = f"Action failed ({action_name}): {error}"
                            yield {
                                "event": "message",
                                "data": json.dumps({
                                    "type": "tool.failed",
                                    "tool": action_name,
                                    "requestId": action_request.request_id,
                                    "error": error,
                                }),
                            }
                elif decision == "deny":
                    tool_context = f"Action denied by the user: {action_name}"
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "tool.denied",
                            "tool": action_name,
                            "requestId": action_request.request_id,
                        }),
                    }
                else:
                    tool_context = f"Action expired before approval: {action_name}"
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "tool.expired",
                            "tool": action_name,
                            "requestId": action_request.request_id,
                        }),
                    }

        provider_prompt = f"{system_prompt}\n\n{tool_context}" if tool_context else system_prompt

        # Stream content from inference adapter
        try:
            async for event in provider_service.stream_chat_completion(
                model=selected_model,
                messages=formatted_history,
                system_prompt=provider_prompt
            ):
                if event["type"] == "content.delta":
                    accumulated_text += event["delta"]
                    yield {
                        "event": "message",
                        "data": json.dumps({
                            "type": "content.delta",
                            "botMsgId": bot_msg_id,
                            "delta": event["delta"]
                        })
                    }
                elif event["type"] == "turn.completed":
                    ok = event.get("ok", True)
                    if ok:
                        bot_msg = {
                            "id": bot_msg_id,
                            "thread_id": thread_id,
                            "bot_id": thread_id,
                            "sender": "bot",
                            "text": accumulated_text,
                            "created_at": datetime.now().isoformat(),
                            "model": selected_model,
                            "item_type": "assistant_text"
                        }
                        storage_service.add_message(bot_msg)
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "turn.completed", "ok": ok, "botMsgId": bot_msg_id})
                    }
        except asyncio.CancelledError:
            raise

    return EventSourceResponse(event_generator())
