"""OAuth login, callback, current account and logout routes.

Login is intentionally a browser redirect flow. Provider tokens live only in
the callback request; the browser receives an ApiPilot HttpOnly session cookie.
"""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Path, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from backend.api.deps import CurrentUserDep, SessionDep
from backend.api.errors import ERROR_RESPONSES, AppError
from backend.schemas.auth import (
    AuthConfigResponse,
    AuthProviderStatus,
    CurrentUserResponse,
)
from backend.services import auth as auth_service
from backend.services.auth import AuthError
from backend.services.auth_config import (
    AUTH_COOKIE_NAME,
    OAUTH_STATE_COOKIE_NAME,
    SAFE_PROVIDER_NAMES,
    AuthSettings,
    safe_next_path,
)
from backend.services.oauth import OAuthService

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ProviderName = Annotated[str, Path(description="github or google")]


def _settings(request: Request) -> AuthSettings:
    return request.app.state.auth.settings


def _oauth(request: Request) -> OAuthService:
    return request.app.state.auth


def _login_error(settings: AuthSettings, code: str, next_path: str | None = None) -> RedirectResponse:
    query = {"error": code}
    if next_path:
        query["next"] = safe_next_path(next_path)
    return RedirectResponse(
        settings.frontend_base_url.rstrip("/") + "/login?" + urlencode(query),
        status_code=status.HTTP_302_FOUND,
    )


def _set_cookie(response: Response, token: str, settings: AuthSettings) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/", samesite="lax")


def _as_public_user(user) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=str(user.id),
        name=user.username,
        email=user.email,
        avatar_url=user.avatar_url,
        provider=user.provider,
    )


@router.get(
    "/config",
    response_model=AuthConfigResponse,
    summary="Read the deployment auth mode and provider availability",
    responses=ERROR_RESPONSES,
)
async def auth_config(request: Request) -> AuthConfigResponse:
    settings = _settings(request)
    providers = [
        AuthProviderStatus(id=name, configured=settings.provider_configured(name))
        for name in ("github", "google")
    ]
    return AuthConfigResponse(
        deployment_mode=settings.deployment_mode,
        login_required=settings.login_required,
        guest_enabled=settings.guest_experience_enabled,
        providers=providers,
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Read the signed-in account",
    responses=ERROR_RESPONSES,
)
async def current_user(user: CurrentUserDep) -> CurrentUserResponse:
    return _as_public_user(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current account session",
    responses=ERROR_RESPONSES,
)
async def logout(request: Request, session: SessionDep) -> Response:
    settings = _settings(request)
    token = request.cookies.get(AUTH_COOKIE_NAME)
    await auth_service.revoke_session(session, token)
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookie(response)
    # The state cookie is not needed after login; clear it when possible.
    response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    return response


@router.get(
    "/login/{provider}",
    summary="Start a GitHub or Google login",
    responses=ERROR_RESPONSES,
)
async def begin_login(
    request: Request,
    provider: ProviderName,
    session: SessionDep,
    next_path: Annotated[str | None, Query(alias="next")] = None,
) -> RedirectResponse:
    settings = _settings(request)
    if not settings.official_cloud:
        raise AppError(
            404,
            code="auth-disabled",
            message_key="auth.errors.providerUnavailable",
        )
    if provider not in SAFE_PROVIDER_NAMES:
        raise AppError(
            404,
            code="provider-not-found",
            message_key="auth.errors.providerUnavailable",
        )
    if not _oauth(request).configured(provider):
        return _login_error(settings, "provider-unavailable", next_path)

    try:
        return await _oauth(request).start(
            request,
            session,
            provider=provider,
            redirect_after=safe_next_path(next_path),
        )
    except AuthError as exc:
        return _login_error(settings, exc.code, next_path)
    except Exception:
        logger.exception("could not start OAuth provider %s", provider)
        return _login_error(settings, "oauth-failed", next_path)


@router.get(
    "/callback/{provider}",
    summary="OAuth callback",
    responses=ERROR_RESPONSES,
)
async def oauth_callback(
    request: Request,
    provider: ProviderName,
    session: SessionDep,
) -> RedirectResponse:
    settings = _settings(request)
    if not settings.official_cloud:
        raise AppError(
            404,
            code="auth-disabled",
            message_key="auth.errors.providerUnavailable",
        )
    if provider not in SAFE_PROVIDER_NAMES:
        raise AppError(
            404,
            code="provider-not-found",
            message_key="auth.errors.providerUnavailable",
        )

    try:
        identity, next_path = await _oauth(request).complete(
            request, session, provider=provider
        )
        user = await auth_service.create_or_get_user(session, identity)
        await auth_service.internal_guest_for_user(session, user)
        _account_session, token = await auth_service.issue_session(session, user, settings)
        await session.commit()
    except AuthError as exc:
        await session.rollback()
        return _login_error(settings, exc.code)
    except Exception:
        await session.rollback()
        logger.exception("OAuth callback failed for provider %s", provider)
        return _login_error(settings, "oauth-failed")

    response = RedirectResponse(
        settings.redirect_after_login(next_path),
        status_code=status.HTTP_302_FOUND,
    )
    _set_cookie(response, token, settings)
    return response
