from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.task import TaskCreateRequest, TaskResponse
from app.services import task_execution_service
from app.services.task_execution_service import (
    UnsupportedProviderError,
    BoxCommandError,
    TaskNotFoundError,
    ParentTaskActiveError,
)
from app.services.user_credential_service import CredentialNotFoundError

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(user_id: str, db: AsyncSession = Depends(get_db)):
    return await task_execution_service.list_tasks_for_user(db, user_id)


@router.post("", response_model=TaskResponse)
async def create_task(
    payload: TaskCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await task_execution_service.execute_task(
            db,
            user_id=payload.user_id,
            provider=payload.provider,
            box_id=payload.box_id,
            prompt_text=payload.prompt_text,
            parent_task_id=payload.parent_task_id,
        )
    except UnsupportedProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ParentTaskActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except BoxCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await task_execution_service.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return await task_execution_service.sync_task_status(db, task)
