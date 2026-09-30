from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A session bound to a transaction that's always rolled back, so tests
    never leave rows behind in the real database.

    Uses its own engine (rather than the app's shared one) because
    pytest-asyncio runs each test in its own event loop by default, and an
    asyncpg connection pool can't be reused across loops.
    """
    engine = create_async_engine(settings.ASYNC_DATABASE_URL)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def user_id() -> str:
    return "test-user-1"


@pytest.fixture
def other_user_id() -> str:
    return "test-user-2"
