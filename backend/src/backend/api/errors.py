"""The error envelope, and the handlers that produce it.

Every non-2xx response this service emits has the same shape::

    {"code": "...", "messageKey": "...", "params": {...}}

``code``       machine-readable, stable, ours.  Used for branching and log
               aggregation -- never rendered.
``messageKey`` an i18n key the frontend resolves from its own dictionary.
               ``frontend/src/stores/locale.ts`` returns the key *itself* on a
               miss, so an unknown key renders to the user as
               ``console.runs.errors.something``.  Only keys in
               ``RUN_MESSAGE_KEYS`` below will render as sentences.
``params``     interpolation values.  **Omitted entirely when empty -- never
               ``null``.**  The frontend's ``interpolate()`` calls
               ``Object.prototype.hasOwnProperty.call(params, ...)``, which
               throws ``TypeError`` on ``null`` whenever the sentence contains a
               placeholder -- and ``console.runs.errors.notApproved`` is
               ``"“{plan}” has to be approved before it can run."``.  A ``null``
               here is a blank page, not a cosmetic flaw.  ``build_error_payload``
               is the only place the key is added, so the rule has one home.

Diagnostics go under ``details``, not ``params``: the frontend types ``params``
as ``Record<string, string | number>``, so an array or an object cannot live
there without lying about the type.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.schemas.common import ErrorResponse

__all__ = [
    "AppError",
    "AUTH_REQUIRED_CODE",
    "ERROR_RESPONSES",
    "GUEST_SESSION_REQUIRED_CODE",
    "RUN_MESSAGE_KEYS",
    "UNAUTHORIZED_MESSAGE_KEY",
    "auth_required",
    "guest_session_required",
    "SQLSTATE_CHECK_VIOLATION",
    "SQLSTATE_EXCLUSION_VIOLATION",
    "SQLSTATE_FOREIGN_KEY_VIOLATION",
    "SQLSTATE_UNIQUE_VIOLATION",
    "build_error_payload",
    "constraint_of",
    "register_exception_handlers",
]

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""Methods that read.  Used to pick which sentence a validation failure gets."""


# --------------------------------------------------------------------------- #
# The keys the frontend can actually render
# --------------------------------------------------------------------------- #

AUTH_REQUIRED_CODE = "auth-required"
"""An official-cloud request without a valid account session."""

GUEST_SESSION_REQUIRED_CODE = "guest-session-required"
"""The one code a missing, malformed, unknown, expired or revoked credential gets.

One code for five causes, on purpose: the client's next move is the same in every
case (obtain a session), and distinguishing them would tell a caller whether a
token it guessed names a real row (identity contract, section 6.4).
"""

UNAUTHORIZED_MESSAGE_KEY = "console.runs.errors.unauthorized"
"""The sentence for that code.  It has to be in the frontend's dictionary too --
until it is, a 401 renders as the key itself (see the identity contract, 6.4)."""


def auth_required() -> "AppError":
    """The 401 for an official-cloud route without a valid account session."""
    return AppError(
        401,
        code=AUTH_REQUIRED_CODE,
        message_key="auth.errors.required",
    )


def guest_session_required() -> "AppError":
    """The 401 the identity dependency raises.  Never carries the token."""
    return AppError(
        401,
        code=GUEST_SESSION_REQUIRED_CODE,
        message_key=UNAUTHORIZED_MESSAGE_KEY,
    )


RUN_MESSAGE_KEYS: frozenset[str] = frozenset(
    {
        "console.runs.errors.title",
        UNAUTHORIZED_MESSAGE_KEY,
        "console.runs.errors.notFound",
        "console.runs.errors.notApproved",
        "console.runs.errors.noPlan",
        "console.runs.errors.createFailed",
        "console.runs.errors.loadFailed",
        "console.runs.errors.cancelFailed",
        "console.runs.errors.dismiss",
        "console.runs.failure.notExecutable",
        "console.report.notFound",
        "console.report.notReady",
        "console.report.generateFailed",
        "auth.errors.required",
        "auth.errors.providerUnavailable",
        "auth.errors.guestSessionsDisabled",
        "auth.errors.guestLimitReached",
        "auth.errors.forbiddenOrigin",
    }
)
"""The nine run-related keys present in ``frontend/src/locales/console/en-US.ts``.

Anything outside this set renders as the raw key.  It is a constant rather than
an enforced allowlist because *whose dictionary is authoritative* is an open
question -- mirroring the frontend's, having the backend own one, and shipping a
pre-localised sentence are all defensible, and they cost different amounts.  Once
that is settled, ``build_error_payload`` is the single place to enforce it.
"""


# --------------------------------------------------------------------------- #
# Error type
# --------------------------------------------------------------------------- #


class AppError(Exception):
    """An error with a decided HTTP status and a client-renderable body.

    Raise this from a service; the handler below turns it into the envelope.
    Anything else that escapes a route is a bug, and becomes a 500.
    """

    def __init__(
        self,
        status_code: int,
        *,
        code: str,
        message_key: str,
        params: Mapping[str, str | int] | None = None,
        details: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status_code} {code}")
        self.status_code = status_code
        self.code = code
        self.message_key = message_key
        self.params: dict[str, str | int] = dict(params or {})
        self.details = details
        self.headers = dict(headers) if headers else None


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #


def _jsonable(value: Any) -> Any:
    """Reduce anything to something ``JSONResponse`` can encode.

    ``RequestValidationError.errors()`` carries live exception objects in its
    ``ctx`` entries, so a naive ``dict(exc.errors())`` is not encodable.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def build_error_payload(
    *,
    code: str,
    message_key: str,
    params: Mapping[str, str | int] | None = None,
    details: Any = None,
) -> dict[str, Any]:
    """Assemble the envelope, omitting ``params`` when there is nothing to interpolate.

    ``params`` is popped rather than set to ``None`` so that ``"params" not in
    body`` holds -- see the module docstring for why ``null`` is not an option.
    """
    payload: dict[str, Any] = {"code": code, "messageKey": message_key}
    if params:
        payload["params"] = {str(key): _jsonable(value) for key, value in params.items()}
    if details is not None:
        payload["details"] = _jsonable(details)
    return payload


def _error_response(
    status_code: int,
    *,
    code: str,
    message_key: str,
    params: Mapping[str, str | int] | None = None,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_payload(
            code=code, message_key=message_key, params=params, details=details
        ),
        headers=dict(headers) if headers else None,
    )


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        logger.error(
            "%s %s -> %s %s", request.method, request.url.path, exc.status_code, exc.code,
            exc_info=exc,
        )
    else:
        logger.info(
            "%s %s -> %s %s", request.method, request.url.path, exc.status_code, exc.code
        )
    return _error_response(
        exc.status_code,
        code=exc.code,
        message_key=exc.message_key,
        params=exc.params,
        details=exc.details,
        headers=exc.headers,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 for a body that failed validation.

    **The request body is deliberately not echoed.**  ``exc.body`` would be the
    parsed payload, and for ``POST /api/projects/{project_id}/runs`` that payload
    contains ``variables`` -- live secret values.  Reflecting it into an error
    response, which is logged, cached and rendered, is precisely the leak that
    keeping values out of the database was meant to avoid.

    ``messageKey`` is chosen by method, because a rejected ``GET`` is not a
    failed create.  Until the query parameters on ``GET .../runs`` existed the
    distinction was unreachable -- the only validatable input was a create body
    -- so every envelope said "The run could not be created."  A read that
    refuses ``?limit=0`` renders through the same key the frontend uses for a
    load failure, which is what the REST contract asks for; a write keeps the
    create key.
    """
    message_key = (
        "console.runs.errors.loadFailed"
        if request.method in _SAFE_METHODS
        else "console.runs.errors.createFailed"
    )
    logger.info("%s %s -> 422 invalid-request", request.method, request.url.path)
    return _error_response(
        422,
        code="invalid-request",
        message_key=message_key,
        details={"errors": exc.errors()},
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Starlette's own exceptions, in the same envelope.

    Without this, an unknown path and a wrong method return ``{"detail": ...}``
    while every other failure returns the envelope -- two shapes, and the
    frontend's error adapter would have to know about both.
    """
    detail = exc.detail if isinstance(exc.detail, str) else None
    return _error_response(
        exc.status_code,
        code="http-error",
        message_key="console.runs.errors.loadFailed",
        details={"detail": detail} if detail else None,
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. The client gets a code; the traceback goes to the log."""
    logger.exception("%s %s -> 500 internal-error", request.method, request.url.path)
    return _error_response(
        500,
        code="internal-error",
        message_key="console.runs.errors.loadFailed",
        details={"type": type(exc).__name__},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found."},
    409: {"model": ErrorResponse, "description": "Conflicting state, e.g. a plan that is not approved."},
    422: {"model": ErrorResponse, "description": "The request body failed validation."},
    500: {"model": ErrorResponse, "description": "Unhandled server error."},
}
"""Shared ``responses=`` map so the OpenAPI document describes failures too."""


# --------------------------------------------------------------------------- #
# Database constraint errors -- infrastructure, not yet wired
# --------------------------------------------------------------------------- #

SQLSTATE_UNIQUE_VIOLATION = "23505"
SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
SQLSTATE_CHECK_VIOLATION = "23514"
SQLSTATE_EXCLUSION_VIOLATION = "23P01"


def constraint_of(exc: IntegrityError) -> tuple[str | None, str | None]:
    """Return ``(constraint_name, sqlstate)`` for a failed statement.

    The two values live on different objects, which is the whole reason this
    helper exists:

    * ``exc.orig`` is SQLAlchemy's asyncpg adapter error
      (``AsyncAdapt_asyncpg_dbapi.IntegrityError``).  The adapter sets
      ``sqlstate`` and ``pgcode`` on it -- but *not* ``constraint_name``.
    * ``exc.orig.__cause__`` is the original ``asyncpg.exceptions.*Error``, and
      that is where ``constraint_name`` lives.  The adapter raised it with
      ``raise translated_error from error``.

    **Never decide which constraint failed from the message text.**  This
    PostgreSQL returns localised messages, and SQLAlchemy prefixes them with the
    exception's class name, so a regex on English prose fails on a machine that
    is not in English -- which is exactly the machine this one is.

    Returns ``(None, None)`` when the exception did not come through the asyncpg
    translation path, which is possible and not an error in itself.
    """
    adapter = exc.orig
    sqlstate = getattr(adapter, "sqlstate", None) or getattr(adapter, "pgcode", None)
    cause = getattr(adapter, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    return name, sqlstate
