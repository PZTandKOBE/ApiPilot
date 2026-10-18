"""Application assembly.

Everything that shapes the HTTP surface is here, in one screen: middleware,
exception handlers, routers. A reader who wants to know what this service
exposes should not have to follow imports to find out.

Auth is assembled here too: the deployment mode is read once per app factory,
and the OAuth client is attached to app.state so tests can replace the provider
exchange without touching the routes.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.api.errors import build_error_payload, register_exception_handlers
from backend.api.routers import agent, auth, guest_sessions, projects, reports, runs
from backend.services.auth_config import (
    AUTH_COOKIE_NAME,
    OAUTH_STATE_COOKIE_NAME,
    load_auth_settings,
)
from backend.services.oauth import OAuthService

logger = logging.getLogger(__name__)

__all__ = ["CORS_ALLOW_ORIGINS_ENV", "DEFAULT_CORS_ALLOW_ORIGINS", "allowed_origins", "create_app"]

CORS_ALLOW_ORIGINS_ENV = "CORS_ALLOW_ORIGINS"

DEFAULT_CORS_ALLOW_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
"""Vite's dev server, by name and by address.

An explicit list, not ["*"]. A wildcard on a service that carries credentials
would also be what ships; deployments add their origin through the environment
variable instead.
"""


def allowed_origins() -> list[str]:
    raw = os.getenv(CORS_ALLOW_ORIGINS_ENV, DEFAULT_CORS_ALLOW_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown around run recovery.

    Recovery is a repair, not a prerequisite: a database that is unreachable at
    boot must not turn a small cleanup problem into an outage. It is skipped by
    the executor's existing disabled switch.
    """
    from backend.services.run_executor import recover_queued_runs

    try:
        await recover_queued_runs()
    except Exception:
        logger.exception("startup: run recovery failed; the server will still start")

    yield


def create_app() -> FastAPI:
    settings = load_auth_settings()

    app = FastAPI(
        lifespan=_lifespan,
        title="ApiPilot API",
        version="0.1.0",
        summary="Run test plans against a real API and report what happened.",
        description=(
            "Runs are created from a plan, its OpenAPI document, an environment "
            "and a set of variables; the run record and its rows are then the "
            "property of the server, and the client only reads them. Agent tasks "
            "are the other way in: a document and a prompt in, a draft plan out, "
            "and no run until a human approves it.\n\n"
            "Errors all share one envelope: code, messageKey and, when there "
            "is something to interpolate, params."
        ),
    )

    app.state.auth = OAuthService(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.state_secret:
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.state_secret,
            session_cookie=OAUTH_STATE_COOKIE_NAME,
            max_age=settings.state_ttl_seconds,
            same_site="lax",
            https_only=settings.session_cookie_secure,
            path="/",
        )

    @app.middleware("http")
    async def auth_origin_guard(request: Request, call_next):
        """Reject a cross-site cookie-authenticated write.

        The account cookie is SameSite=Lax; this is the second line for a
        same-site-but-wrong-origin or a browser that sends an Origin header.
        Non-browser clients without Origin are not blocked by this check.
        """
        current = request.app.state.auth.settings
        if (
            current.official_cloud
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and request.cookies.get(AUTH_COOKIE_NAME)
        ):
            origin = request.headers.get("origin")
            if origin and origin not in current.allowed_origins():
                return JSONResponse(
                    status_code=403,
                    content=build_error_payload(
                        code="forbidden-origin",
                        message_key="auth.errors.forbiddenOrigin",
                    ),
                )
        return await call_next(request)

    register_exception_handlers(app)
    app.include_router(auth.router)
    app.include_router(guest_sessions.router)
    app.include_router(projects.router)
    app.include_router(runs.router)
    app.include_router(reports.router)
    app.include_router(agent.router)

    return app
