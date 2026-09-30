from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime
import uuid
from pydantic import ValidationError
from app.services.computer_provider import computer_provider, ComputerProviderError

from app.schemas.contracts import Bot
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/bots", tags=["bots"])

@router.get("", response_model=List[Bot])
async def get_bots():
    return storage_service.get_bots()

@router.post("", response_model=Bot)
async def create_bot(bot_data: Dict[str, Any]):
    allowed = {"name", "role", "description", "avatar", "model", "accent_color", "system_prompt", "tools", "pinned", "unread_count"}
    unknown = set(bot_data) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported bot fields: {', '.join(sorted(unknown))}")
    if "id" in bot_data:
        raise HTTPException(status_code=422, detail="Bot ids are assigned by the server.")
    new_id = f"bot-{uuid.uuid4().hex}"
    bot = {
        "id": new_id,
        "name": bot_data.get("name", "New Bot"),
        "role": bot_data.get("role", "AI Assistant"),
        "description": bot_data.get("description", "Custom AI agent persona"),
        "avatar": bot_data.get("avatar", "🤖"),
        "model": bot_data.get("model", storage_service.get_settings()["default_model"]),
        "accent_color": bot_data.get("accent_color", "#3b82f6"),
        "system_prompt": bot_data.get("system_prompt", "You are a helpful AI assistant."),
        "tools": bot_data.get("tools", []),
        "pinned": False,
        "unread_count": 0,
        "created_at": datetime.now().isoformat()
    }
    try:
        bot = Bot.model_validate(bot).model_dump()
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    bots = storage_service.get_bots()
    bots.append(bot)
    storage_service.save_bots(bots)
    return bot

@router.put("/{bot_id}", response_model=Bot)
async def update_bot(bot_id: str, updates: Dict[str, Any]):
    allowed = {"name", "role", "description", "avatar", "model", "accent_color", "system_prompt", "tools", "pinned", "unread_count"}
    unknown = set(updates) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported bot fields: {', '.join(sorted(unknown))}")
    bots = storage_service.get_bots()
    for i, b in enumerate(bots):
        if b["id"] == bot_id:
            candidate = {**b, **updates, "id": bot_id}
            try:
                bots[i] = Bot.model_validate(candidate).model_dump()
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail=exc.errors()) from exc
            storage_service.save_bots(bots)
            return bots[i]
    raise HTTPException(status_code=404, detail="Bot not found")

@router.delete("/{bot_id}")
async def delete_bot(bot_id: str):
    bots = storage_service.get_bots()
    if not any(bot["id"] == bot_id for bot in bots):
        raise HTTPException(status_code=404, detail="Bot not found")
    # Describe-only: the delete path must never provision a runtime record or
    # workspace directory just to tear it down. cleanup() recovers an existing
    # container from Docker on its own when needed.
    status = computer_provider.describe(bot_id)
    try:
        await computer_provider.cleanup(status.computer_id)
    except ComputerProviderError as exc:
        raise HTTPException(status_code=409, detail=f"Could not clean up the bot computer: {exc}") from exc
    storage_service.delete_bot(bot_id)
    return {"status": "ok", "deleted_id": bot_id}
