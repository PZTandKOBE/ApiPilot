"""Request-scoped dependencies.

Two identities, one ownership model:

* self-hosted: the verified X-Guest-Session browser token, exactly as before;
* official cloud: an account cookie mapped to the account's server-side
  internal guest identity, or -- when explicitly enabled -- a verified browser
  guest token. The account session is verified here, not trusted from
  localStorage, and the existing project/run/report ownership checks still run
  in the services.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import auth_required, guest_session_required
from backend.db.database import AsyncSessionLocal
from backend.db.models.user import GuestSession, User
from backend.services import auth as auth_service
from backend.services import guest_session
from backend.services.auth_config import AUTH_COOKIE_NAME, AuthSettings

__all__ = [
    "CurrentGuestSessionDep",
    "CurrentUserDep",
    "GuestToken",
    "SessionDep",
    "get_current_guest_session",
    "get_current_user",
    "get_session",
]


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session, rolling back on any exception."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]

GuestToken = Annotated[
    str | None,
    Header(
        alias="X-Guest-Session",
        description=(
            "The token returned by POST /api/guest-sessions. Accepted in "
            "self-hosted mode, and in official cloud only when the deployment "
            "explicitly enables guest experience."
        ),
    ),
]


def _settings(request: Request) -> AuthSettings:
    return request.app.state.auth.settings


async def get_current_user(request: Request, session: SessionDep) -> User:
    """The account session behind the HttpOnly cookie, or a 401."""
    settings = _settings(request)
    if not settings.official_cloud:
        raise auth_required()

    token = request.cookies.get(AUTH_COOKIE_NAME)
    user = await auth_service.user_for_session_token(session, token)
    if user is None:
        raise auth_required()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def _internal_guest(session: AsyncSession, user: User) -> GuestSession:
    found = await session.execute(
        select(GuestSession).where(GuestSession.user_id == user.id)
    )
    guest = found.scalar_one_or_none()
    if guest is None or guest.revoked_at is not None:
        raise auth_required()
    return guest


async def get_current_guest_session(
    request: Request,
    session: SessionDep,
    token: GuestToken = None,
) -> GuestSession:
    """Resolve the browser identity appropriate to this deployment.

    An account cookie always wins over a guest token. In official cloud the
    guest header is accepted only when the deployment explicitly enables guest
    experience; its server-side row is still the same ownership bridge used by
    self-hosted guests. Account users keep the internal user_id bridge.
    """
    settings = _settings(request)

    if settings.official_cloud:
        user = await auth_service.user_for_session_token(
            session, request.cookies.get(AUTH_COOKIE_NAME)
        )
        if user is not None:
            return await _internal_guest(session, user)
        if not settings.official_guest_enabled:
            raise auth_required()
        guest = await guest_session.verify(session, token)
        if guest is None:
            raise guest_session_required()
        if guest_session.is_due_for_renewal(guest):
            await guest_session.renew(token or "")
        return guest

    guest = await guest_session.verify(session, token)
    if guest is None:
        raise guest_session_required()

    if guest_session.is_due_for_renewal(guest):
        await guest_session.renew(token or "")

    return guest


CurrentGuestSessionDep = Annotated[GuestSession, Depends(get_current_guest_session)]
