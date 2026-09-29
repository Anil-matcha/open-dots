import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.background import run_every
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.routers.router import router as app_router
from app.services import schedule_service, task_execution_service

BACKGROUND_INTERVAL_SECONDS = 30


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs = [
        asyncio.create_task(
            run_every(BACKGROUND_INTERVAL_SECONDS, schedule_service.poll_due_schedules)
        ),
        asyncio.create_task(
            run_every(BACKGROUND_INTERVAL_SECONDS, task_execution_service.sync_active_tasks)
        ),
        asyncio.create_task(
            run_every(BACKGROUND_INTERVAL_SECONDS, schedule_service.report_finished_runs)
        ),
    ]
    yield
    for job in jobs:
        job.cancel()
    await asyncio.gather(*jobs, return_exceptions=True)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGIN_LIST,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(app_router)
