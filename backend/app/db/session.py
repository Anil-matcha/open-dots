from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(settings.ASYNC_DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with AsyncSessionLocal() as session:
        yield session
