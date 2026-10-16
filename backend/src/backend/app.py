"""Application assembly.

Everything that shapes the HTTP surface is here, in one screen: middleware,
exception handlers, routers.  A reader who wants to know what this service
exposes should not have to follow imports to find out.

``create_app()`` is a factory rather than a module-level ``app`` so that a test
can build a fresh instance with different environment variables -- CORS origins
are read from the environment at call time, not at import time.

The lifespan hook is the other half of that: it is where the process does the one
thing that has to happen before it answers anybody, which today is closing the
runs a previous process left queued.  See ``_lifespan`` below.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.errors import register_exception_handlers
from backend.api.routers import agent, guest_sessions, projects, runs

logger = logging.getLogger(__name__)

__all__ = ["CORS_ALLOW_ORIGINS_ENV", "DEFAULT_CORS_ALLOW_ORIGINS", "allowed_origins", "create_app"]

CORS_ALLOW_ORIGINS_ENV = "CORS_ALLOW_ORIGINS"

DEFAULT_CORS_ALLOW_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
"""Vite's dev server, by name and by address.

An explicit list, not ``["*"]``.  The frontend has no API base URL configured
yet and no Vite proxy, so in development it calls this service cross-origin
directly -- which means without CORS the very first request fails and nothing
else can be tested.  But ``*`` would also be what ships, and a wildcard on a
service that will eventually carry credentials is a decision nobody makes on
purpose.  Add deployments through the environment variable instead.
"""


def allowed_origins() -> list[str]:
    """Parse ``CORS_ALLOW_ORIGINS``, falling back to the Vite dev server.

    Comma-separated, in the same ``os.getenv`` style as
    ``backend/db/database.py``.  ``.env`` has already been read by the time this
    runs: ``backend.db.database`` calls ``load_dotenv()`` at import.
    """
    raw = os.getenv(CORS_ALLOW_ORIGINS_ENV, DEFAULT_CORS_ALLOW_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown for the process, around the serving of requests.

    The only startup work is run recovery, and it is here rather than in a router
    because it is about the *process*: a run left ``queued`` by a process that died
    will never be picked up by anything else, and the moment to notice is before
    the server starts accepting work.

    Two properties matter more than the work itself.

    **It cannot stop the application.**  A database that is unreachable at boot, a
    row that cannot be read, a repair that fails -- all of them are logged and the
    server starts anyway.  Recovery is a repair, not a prerequisite, and a service
    that refused to start because it could not tidy up would turn a small problem
    into an outage.

    **It is off when execution is off.**  ``recover_queued_runs`` returns
    immediately when ``RUN_EXECUTOR_DISABLED`` is set, which is what the
    verification scripts rely on: their runs are fixtures that must stay exactly as
    they were created, and a recovery pass that ran anyway would rewrite them.
    """
    from backend.services.run_executor import recover_queued_runs

    try:
        await recover_queued_runs()
    except Exception:
        logger.exception("startup: run recovery failed; the server will still start")

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=_lifespan,
        title="AI API Testing Agent API",
        version="0.1.0",
        summary="Run test plans against a real API and report what happened.",
        description=(
            "Runs are created from a plan, its OpenAPI document, an environment "
            "and a set of variables; the run record and its rows are then the "
            "property of the server, and the client only reads them. Agent tasks "
            "are the other way in: a document and a prompt in, a draft plan out, "
            "and no run until a human approves it.\n\n"
            "Errors all share one envelope: `code`, `messageKey` and, when there "
            "is something to interpolate, `params`."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(guest_sessions.router)
    app.include_router(projects.router)
    app.include_router(runs.router)
    app.include_router(agent.router)

    return app
