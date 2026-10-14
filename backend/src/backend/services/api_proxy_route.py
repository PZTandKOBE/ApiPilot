"""Route-facing entry point for the request proxy.

`backend.services.api_proxy` decides *whether* a target may be reached and
`forward` performs the call.  This module is the thin seam the router talks to,
and it exists for one reason worth writing down: **the authorization check and
the outbound work must be in an order the router cannot get wrong.**
`proxy_for_guest` takes the ownership check as an awaited call and performs it
before it does anything else, so a route cannot accidentally resolve a name or
open a socket for a caller who owns nothing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import AppError
from backend.db.models.user import GuestSession
from backend.schemas.proxy import ProxyRequest, ProxyResponse
from backend.services import api_proxy, guest_access

__all__ = ["PROXY_FAILED_MESSAGE_KEY", "proxy_for_guest"]

PROXY_FAILED_MESSAGE_KEY = "console.apiClient.error.network"
"""The sentence a refused or failed call reports.  It is a key the API Client
already renders for a transport failure, so the client needs no new vocabulary to
show one of these."""

_BLOCKED_STATUS = {
    api_proxy.TIMEOUT_CODE: 504,
    api_proxy.BLOCKED_TARGET_CODE: 400,
    api_proxy.INVALID_REQUEST_CODE: 400,
    api_proxy.TARGET_UNREACHABLE_CODE: 502,
    api_proxy.BODY_TOO_LARGE_CODE: 502,
    api_proxy.UPSTREAM_FAILED_CODE: 502,
}
"""Where each refusal lands.

A blocked target and a malformed request are the *caller's* problem -- 4xx.  A
timeout, an unreachable host and a response over the cap are the gateway's --
5xx.  The split matters because it is what a client's retry logic and its
reporting both read.
"""


async def proxy_for_guest(
    session: AsyncSession,
    *,
    guest: GuestSession,
    project_id: str,
    payload: ProxyRequest,
) -> ProxyResponse:
    """Authorize the caller against the project, then forward the request.

    The authorization call is the first statement.  Everything expensive and
    everything visible on the network happens after it, which is what the access
    tests measure: a refusal must not produce a DNS query, let alone a connection.
    In the route this is belt and braces -- the ownership check is already a
    dependency, so it has run before the handler exists -- and it is repeated here
    because this function is also the seam a future caller would use directly.
    """
    await guest_access.require_guest_project_access(
        session, project_public_id=project_id, guest=guest
    )

    try:
        return await api_proxy.forward(payload)
    except api_proxy.ProxyError as exc:
        raise AppError(
            _BLOCKED_STATUS.get(exc.code, 502),
            code=exc.code,
            message_key=api_proxy.MESSAGE_KEYS.get(exc.code, PROXY_FAILED_MESSAGE_KEY),
        ) from exc
