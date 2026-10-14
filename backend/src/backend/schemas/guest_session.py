"""Guest session wire schemas.

Phase 8.5 Step 2.  One response shape, for one call: the session that was just
issued.

**The token appears here and nowhere else.**  It is returned exactly once, on
creation, because the server keeps only its digest -- there is no endpoint that
can hand it back, and the schema has no field a digest could travel in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from backend.schemas.base import Schema

__all__ = ["GuestSessionResponse"]


class GuestSessionResponse(Schema):
    """A freshly issued guest session.

    `session_token` is the credential itself: the browser sends it back in the
    `X-Guest-Session` header.  This is the only response in the service that
    carries it, and the only time it exists on the server is between being
    generated and being hashed.
    """

    session_token: str = Field(
        description=(
            "The opaque session token, returned exactly once. Send it in the "
            "X-Guest-Session header; the server stores only its SHA-256 digest."
        )
    )
    created_at: datetime
    expires_at: datetime = Field(
        description="When the session stops being valid unless activity renews it."
    )
