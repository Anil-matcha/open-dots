import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


async def run_every(seconds: float, job: Callable[[], Awaitable[None]]) -> None:
    # Sleeps after each run finishes, so runs of the same job never overlap.
    while True:
        try:
            await job()
        except Exception:
            logger.exception("background job failed", job=job.__name__)
        await asyncio.sleep(seconds)
