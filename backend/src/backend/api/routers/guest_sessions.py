"""Guest session endpoints.

Phase 8.5 Step 2.  Two routes, and they are the only two this step adds:

* `POST /api/guest-sessions` -- public: it is how a caller comes to have an
  identity at all, so it cannot require one.  The token it returns is the only
  copy the server will ever hand out.
* `DELETE /api/guest-sessions/current` -- authenticated, and "current" is
  deliberate: there is no route that revokes a session by id, so a caller cannot
  end somebody else's session even by naming it.

**Nothing here is rate limited.**  An open endpoint that writes a row per call is
a denial-of-service surface; the deployment answer (a reverse proxy or a limiter
in front) is recorded as deferred in the Phase 8.5 Step 2 report rather than
invented here.

The header is `X-Guest-Session` and it is read only through
`CurrentGuestSessionDep`; no route in this service reads a token from the query
string or treats a project, task or run id as a credential (identity contract,
section 6.2).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from backend.api.deps import CurrentGuestSessionDep, SessionDep
from backend.api.errors import ERROR_RESPONSES
from backend.schemas.common import ErrorResponse
from backend.schemas.guest_session import GuestSessionResponse
from backend.services import guest_session

__all__ = ["GUEST_ERROR_RESPONSES", "router"]

router = APIRouter(prefix="/api", tags=["guest"])

GUEST_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ErrorResponse,
        "description": "No valid guest session: missing, malformed, unknown, expired or revoked.",
    },
    **ERROR_RESPONSES,
}
"""The shared map plus the status this router is the first to answer."""


@router.post(
    "/guest-sessions",
    response_model=GuestSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a guest session",
    responses=ERROR_RESPONSES,
)
async def create_guest_session(session: SessionDep) -> GuestSessionResponse:
    """Issue a guest session and return its token -- once.

    The request carries no body: a caller cannot choose its own id, its own
    digest, its own expiry or its own ownership, so there is nothing to validate
    and nothing to smuggle in.  The token is generated server-side from 256 bits
    of `secrets` randomness, stored as a SHA-256 digest, and returned here for
    the only time.

    `201 Created` with the token, the moment it was created and the moment it
    expires.  The digest is not in the response and has no field to travel in.
    """
    guest, token = await guest_session.issue(session)
    await session.commit()

    return GuestSessionResponse(
        session_token=token,
        created_at=guest.created_at,
        expires_at=guest.expires_at,
    )


@router.delete(
    "/guest-sessions/current",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current guest session",
    responses=GUEST_ERROR_RESPONSES,
)
async def revoke_current_guest_session(
    guest: CurrentGuestSessionDep, session: SessionDep
) -> Response:
    """Revoke the session this request authenticated with.

    Immediately and permanently: after this commits, the token is refused by
    verification, and renewal refuses it too, so it cannot be brought back by
    using it.  Revoking is idempotent -- a second call is a no-op -- and there is
    no way to name another session, which is why the route says `current`
    instead of taking an id.

    `204 No Content`: there is nothing to say beyond "done".
    """
    await guest_session.revoke(session, guest)
    await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
