"""Guest identity: issue a session, verify a token, renew it, revoke it.

Phase 8.5 Step 2, and the backend half of `docs/identity-access-contract.md`.
Nothing here is a route and nothing here is a router's opinion: this module owns
the three facts the contract freezes -- how a token is generated, what the
database is allowed to remember about it, and when a session stops being valid.

**The database never sees the token.**  A session stores the SHA-256 digest of
the token and nothing else, so a stolen dump cannot be replayed as credentials.
The raw token exists in exactly two places: the response that issued it, and the
browser that stored it.  It is never logged, never put in an exception and never
returned by anything except the issue call.

**One clock, one order.**  Verification hashes the token, looks the row up,
checks revocation and only then checks expiry -- and it never writes.  Whether a
verified session is *touched* is a separate decision
(:func:renew), because touching is bookkeeping that must not commit a caller's
business transaction and must not happen more than once a day.

**Nothing distinguishes the failures.**  A missing header, a malformed token, an
unknown digest, an expired session and a revoked one all come back as `None`:
the caller turns that into one 401, and a client cannot use the error to learn
whether a given token names a real session.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import AsyncSessionLocal
from backend.db.models.user import GuestSession

__all__ = [
    "RENEWAL_INTERVAL",
    "SESSION_TTL",
    "TOKEN_ENTROPY_BYTES",
    "find_by_hash",
    "find_by_token",
    "hash_token",
    "is_due_for_renewal",
    "issue",
    "renew",
    "revoke",
    "verify",
]

logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(days=30)
"""How long a session lasts, and what activity renews it to."""

RENEWAL_INTERVAL = timedelta(hours=24)
"""How stale a session has to be before using it writes anything."""

TOKEN_ENTROPY_BYTES = 32
"""256 bits of `secrets` randomness.  URL-safe because it travels in a header."""


def generate_token() -> str:
    """A fresh opaque token.  The only place one is created."""
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_token(token: str) -> str:
    """The digest stored in `guest_sessions.token_hash`.

    Plain SHA-256, with no salt and no stretching, on purpose: the input is 256
    bits of randomness rather than a password, so there is no dictionary to slow
    down -- and a password-hashing framework here would buy nothing and cost a
    dependency (contract section 4.3).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _moment(now: datetime | None) -> datetime:
    """One clock for the whole module, always UTC-aware.

    Callers may pass a moment (the tests do, so expiry and renewal can be
    exercised without waiting 30 days); otherwise it is read here.
    """
    if now is not None:
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc)


async def issue(
    session: AsyncSession, *, now: datetime | None = None, ttl: timedelta = SESSION_TTL
) -> tuple[GuestSession, str]:
    """Create a session and return it with the only copy of its token.

    The caller commits.  The row is flushed (not committed) so its id exists for
    the response, and refreshed so the server-side `created_at` is the value the
    database actually stored.
    """
    moment = _moment(now)
    token = generate_token()

    guest = GuestSession(
        token_hash=hash_token(token),
        # Created and expiring from the same reading of the clock, so the row's own
        # arithmetic is exact: expires_at - created_at is the TTL, not the TTL minus
        # however long the transaction took to reach the INSERT.
        created_at=moment,
        expires_at=moment + ttl,
        last_seen_at=moment,
        revoked_at=None,
    )
    session.add(guest)
    await session.flush()
    await session.refresh(guest)

    logger.info("issued guest session %s (expires %s)", guest.id, guest.expires_at)

    return guest, token


async def find_by_hash(session: AsyncSession, token_hash: str) -> GuestSession | None:
    """The row with that digest, valid or not.  Diagnostics and tests only."""
    found = await session.execute(
        select(GuestSession).where(GuestSession.token_hash == token_hash)
    )

    return found.scalar_one_or_none()


async def find_by_token(
    session: AsyncSession, token: str | None, *, now: datetime | None = None
) -> GuestSession | None:
    """The session this token names, if it is still usable.

    Read-only by design: the checks are revocation and expiry, in that order, and
    an expired or revoked row is returned as absent rather than as itself.
    """
    if token is None or token.strip() == "":
        return None

    guest = await find_by_hash(session, hash_token(token))

    if guest is None or guest.revoked_at is not None:
        return None

    return guest if guest.expires_at > _moment(now) else None


async def verify(
    session: AsyncSession, token: str | None, *, now: datetime | None = None
) -> GuestSession | None:
    """The contract's verification: header value in, identity or nothing out."""
    return await find_by_token(session, token, now=now)


def is_due_for_renewal(guest: GuestSession, *, now: datetime | None = None) -> bool:
    """Whether using this session should write anything at all."""
    return _moment(now) - guest.last_seen_at >= RENEWAL_INTERVAL


async def renew(token: str, *, now: datetime | None = None) -> bool:
    """Extend an active session, at most once per `RENEWAL_INTERVAL`.

    Two decisions are folded into this one statement:

    * **Its own transaction.**  The identity dependency must not commit the
      caller's business transaction, and a renewal waiting for one would never
      happen on a read-only request -- so this opens its own short session.
    * **Conditional, therefore safe under concurrency.**  Two requests that both
      saw a stale `last_seen_at` race on the same row; the loser's WHERE clause
      no longer matches once the winner commits, so exactly one write lands.  No
      lock is taken and no read-then-write window is left open.

    Returns whether this call was the one that wrote.
    """
    moment = _moment(now)

    async with AsyncSessionLocal() as own:
        result = await own.execute(
            update(GuestSession)
            .where(
                GuestSession.token_hash == hash_token(token),
                GuestSession.revoked_at.is_(None),
                GuestSession.expires_at > moment,
                GuestSession.last_seen_at <= moment - RENEWAL_INTERVAL,
            )
            .values(last_seen_at=moment, expires_at=moment + SESSION_TTL)
        )
        await own.commit()

    renewed = result.rowcount == 1

    if renewed:
        logger.info("renewed a guest session for another %s", SESSION_TTL)

    return renewed


async def revoke(
    session: AsyncSession, guest: GuestSession, *, now: datetime | None = None
) -> bool:
    """End a session now, whatever its expiry says.

    Conditional in the same way renewal is: the first revocation writes, a second
    one is a no-op, and a revoked session can never be renewed afterwards because
    every renewal and verification checks `revoked_at` first.  The caller commits.
    """
    moment = _moment(now)

    result = await session.execute(
        update(GuestSession)
        .where(GuestSession.id == guest.id, GuestSession.revoked_at.is_(None))
        .values(revoked_at=moment)
    )

    revoked = result.rowcount == 1

    if revoked:
        logger.info("revoked guest session %s", guest.id)
        guest.revoked_at = moment
    else:
        await session.refresh(guest)

    return revoked
