"""Request-scoped dependencies.

Two dependencies, one job each: hand a route an AsyncSession (and make sure it
is closed and rolled back on the way out), and hand it the **verified** guest
identity behind the request.  AsyncSessionLocal is imported from
backend.db.database, which is frozen -- the session factory already exists and
this module must not grow a second one.

The identity dependency resolves, verifies and returns the session row; it never
returns the header value, because a string a caller typed is not an identity
until the server has checked it (identity contract, section 6.2).  It also never
commits: a route's transaction belongs to the route, and the one write identity
does need -- the daily renewal -- is made in its own unit by
services/guest_session.renew.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import guest_session_required
from backend.db.database import AsyncSessionLocal
from backend.db.models.user import GuestSession
from backend.services import guest_session

__all__ = [
    "CurrentGuestSessionDep",
    "GuestToken",
    "SessionDep",
    "get_current_guest_session",
    "get_session",
]


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session, rolling back on any exception.

    The rollback is not belt-and-braces.  After an ``IntegrityError`` the
    connection is in an aborted transaction and every subsequent statement fails
    with ``25P02`` until it is rolled back -- so a handler that catches a
    constraint violation and tries to report it would otherwise fail while
    building the error response.  ``expire_on_commit=False`` on the factory
    means the rollback costs nothing on the success path.
    """
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
            "The token returned by POST /api/guest-sessions. The only accepted "
            "way to carry a guest identity; a query parameter is never read as "
            "one, and neither is a business id."
        ),
    ),
]


async def get_current_guest_session(
    session: SessionDep, token: GuestToken = None
) -> GuestSession:
    """The verified guest behind this request, or a 401.

    Missing, malformed, unknown, expired and revoked credentials all fail the
    same way -- one status, one code, one sentence -- so the answer cannot be
    used to probe whether a token names a real session (identity contract, 6.4).

    The dependency reads; it does not commit.  When a session has gone a day
    without use, the renewal is written in its own short transaction, which is
    what keeps read-only routes from silently never renewing anything.
    """
    guest = await guest_session.verify(session, token)

    if guest is None:
        raise guest_session_required()

    if guest_session.is_due_for_renewal(guest):
        await guest_session.renew(token or "")

    return guest


CurrentGuestSessionDep = Annotated[GuestSession, Depends(get_current_guest_session)]
