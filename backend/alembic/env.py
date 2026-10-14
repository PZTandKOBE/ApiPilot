"""Alembic environment.

Two things here are deliberate:

**``import backend.db.models``.** Importing the package is what registers the
tables on ``Base.metadata``; without it autogenerate sees an empty schema and
writes an empty migration rather than reporting a problem.  It is imported for
the side effect and therefore carries a ``noqa``.

**The URL never goes through ``config.set_main_option``.** That call writes into
Alembic's ConfigParser, which interpolates ``%``, so a percent-encoded password
(``p%40ss``) makes it raise before any connection is attempted.  The URL is
built once, in ``backend.db.database``, with ``URL.create`` -- which is also
what makes ``@``, ``:``, ``#`` and ``/`` in a password safe -- and handed
straight to the engine.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

import backend.db.models  # noqa: F401  -- registers every table on Base.metadata
from backend.db.base import Base
from backend.db.database import database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting, for ``--sql`` runs."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Its own engine with NullPool: a migration run is one short-lived
    # connection and should not inherit (or leave behind) the app's pool.
    connectable = create_async_engine(database_url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
