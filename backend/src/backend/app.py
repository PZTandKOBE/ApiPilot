"""Application assembly.

Everything that shapes the HTTP surface is here, in one screen: middleware,
exception handlers, routers.  A reader who wants to know what this service
exposes should not have to follow imports to find out.

``create_app()`` is a factory rather than a module-level ``app`` so that a test
can build a fresh instance with different environment variables -- CORS origins
are read from the environment at call time, not at import time.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.errors import register_exception_handlers
from backend.api.routers import agent, guest_sessions, projects, runs

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


def create_app() -> FastAPI:
    app = FastAPI(
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
