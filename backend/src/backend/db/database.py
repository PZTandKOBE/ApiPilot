"""Engine and session factory.

The connection URL is built once, here, with :meth:`sqlalchemy.URL.create` so
that credentials containing ``@``, ``:``, ``#`` or ``/`` are percent-encoded
correctly.  ``alembic/env.py`` imports ``database_url`` from this module rather
than re-deriving it, so there is exactly one place where the connection string
is assembled.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.db.base import Base

__all__ = [
    "AsyncSessionLocal",
    "Base",
    "database_url",
    "engine",
]

load_dotenv()


database_url: URL = URL.create(
    drivername="postgresql+asyncpg",
    username=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
    port=int(os.getenv("POSTGRES_PORT", "5432")),
    database=os.getenv("POSTGRES_DB"),
)

engine: AsyncEngine = create_async_engine(
    database_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
