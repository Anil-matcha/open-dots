from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from app.schemas.task import TaskResponse
from app.services import schedule_service
from app.services.schedule_service import (
    InvalidScheduleError,
    ScheduleInactiveError,
    ScheduleNotFoundError,
)

router = APIRouter(
    prefix="/schedules",
    tags=["Schedules"],
)


@router.post("", response_model=ScheduleResponse)
async def create_schedule(
    payload: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await schedule_service.create_schedule(db, **payload.model_dump())
    except InvalidScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(user_id: str, db: AsyncSession = Depends(get_db)):
    return await schedule_service.list_schedules(db, user_id)


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int, user_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        return await schedule_service.get_schedule(db, schedule_id, user_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    user_id: str,
    payload: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await schedule_service.update_schedule(
            db, schedule_id, user_id, payload.model_dump(exclude_unset=True)
        )
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int, user_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        await schedule_service.delete_schedule(db, schedule_id, user_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(status_code=204)


@router.post("/{schedule_id}/pause", response_model=ScheduleResponse)
async def pause_schedule(
    schedule_id: int, user_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        return await schedule_service.pause_schedule(db, schedule_id, user_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{schedule_id}/resume", response_model=ScheduleResponse)
async def resume_schedule(
    schedule_id: int, user_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        return await schedule_service.resume_schedule(db, schedule_id, user_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{schedule_id}/run", response_model=ScheduleResponse)
async def run_schedule_now(
    schedule_id: int, user_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        return await schedule_service.run_schedule_now(db, schedule_id, user_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ScheduleInactiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{schedule_id}/runs", response_model=list[TaskResponse])
async def list_schedule_runs(
    schedule_id: int, user_id: str, db: AsyncSession = Depends(get_db)
):
    try:
        return await schedule_service.list_schedule_runs(db, schedule_id, user_id)
    except ScheduleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
