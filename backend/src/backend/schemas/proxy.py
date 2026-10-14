"""Wire schemas for the manual API request proxy.

The proxy forwards one request the user composed in the API Client to the API
they are testing, and hands the answer back unchanged.  The shapes here mirror
`frontend/src/types/api.ts` -- `ResolvedApiRequest` in, `ApiResponse` out -- so
that replacing the frontend's mock transport with this endpoint is a transport
change and nothing above it moves.

**Nothing about ownership may appear in these models.**  Which project a request
belongs to is a path parameter, and the owner of that project is the verified
Guest Session; a body that could name either would be a body that could lie.
`extra="forbid"` inherits from `backend.schemas.base.Schema`, so an attempt to
send `projectId` or `guestSessionId` is a validation error rather than a field
that is quietly ignored.

**`headers` is a list of pairs, not a mapping.**  A call can legitimately repeat a
header name, and case is preserved so the target sees what the user typed.  The
same is true on the way back: `Set-Cookie` appears once per cookie.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from backend.schemas.base import Schema

__all__ = [
    "ProxyCookie",
    "ProxyHeaderPair",
    "ProxyRequest",
    "ProxyResponse",
    "ProxyStatusText",
]

ProxyStatusText = str
"""Kept as a plain string: HTTP/2 carries no reason phrase, and a proxy that
invented one would be reporting something the target never said."""

ProxyMethod = Literal[
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
]
"""The methods a manual request may use.

`CONNECT` is a tunnel request, not a request to a target, and `TRACE` reflects the
request back at the caller; both are refused by omission rather than by a check
that could be forgotten.  `HEAD` is here because it is an ordinary read.
"""


class ProxyHeaderPair(Schema):
    """One header, as the user typed it."""

    name: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=8192)


class ProxyRequest(Schema):
    """One request to forward, already resolved by the client.

    Variable substitution has happened on the client, so `url` here is concrete.
    """

    method: ProxyMethod
    url: str = Field(min_length=1, max_length=4096)
    headers: list[ProxyHeaderPair] = Field(default_factory=list, max_length=100)
    body: str | None = Field(default=None, max_length=1_048_576)
    timeout_ms: int | None = Field(default=None, ge=1, le=60_000)


class ProxyCookie(Schema):
    """One `Set-Cookie` the target sent, split the way the client reads it."""

    name: str
    value: str
    domain: str = ""
    path: str = ""
    http_only: bool = False
    secure: bool = False
    expires: str = ""


class ProxyResponse(Schema):
    """What the target answered.

    The upstream status is reported as-is, including 4xx and 5xx: those are the
    target's answers about the user's request, not failures of this proxy, and
    turning them into proxy errors would hide the thing the user is testing.
    """

    status: int
    status_text: ProxyStatusText
    headers: list[ProxyHeaderPair] = Field(default_factory=list)
    cookies: list[ProxyCookie] = Field(default_factory=list)
    body: str
    content_type: str = ""
    body_truncated: bool = False
    body_encoding: Literal["utf-8", "binary"] = "utf-8"
    time_ms: int
    size_bytes: int
