"""Account identities and server-side ApiPilot sessions.

This module deliberately sits beside the existing guest_session service, not
on top of its browser-token path. The browser guest header remains the identity
for a self-hosted deployment; an account session maps to a server-side internal
guest row so the existing project ownership checks keep working unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models.user import (
    GuestSession,
    OAuthTransaction,
    User,
    UserIdentity,
    UserSession,
)
from backend.services import guest_session
from backend.services.auth_config import AuthSettings

__all__ = [
    "AuthError",
    "OAuthIdentity",
    "consume_transaction",
    "create_or_get_user",
    "create_transaction",
    "hash_token",
    "issue_session",
    "internal_guest_for_user",
    "revoke_session",
    "user_for_session_token",
]

logger = logging.getLogger(__name__)

TOKEN_ENTROPY_BYTES = 32
INTERNAL_GUEST_TTL = timedelta(days=3650)
"""The account's server-side ownership bridge is long-lived; revoking the
browser's account session must not destroy the user's projects."""


class AuthError(Exception):
    """A safe, typed authentication failure.

    The route translates the code to a fixed message key or redirect code;
    no provider description, token or stack trace travels with it.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    subject: str
    username: str | None
    email: str | None
    email_verified: bool
    avatar_url: str | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now(now: datetime | None) -> datetime:
    if now is not None:
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _username_base(identity: OAuthIdentity) -> str:
    raw = (identity.username or "").strip()
    if raw == "":
        raw = identity.provider + "-user"
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    return (value or identity.provider + "-user")[:80]


async def _unique_username(
    session: AsyncSession, identity: OAuthIdentity
) -> str:
    base = _username_base(identity)
    candidate = base
    suffix = 1
    while True:
        found = await session.execute(
            select(User.id).where(User.username == candidate)
        )
        if found.scalar_one_or_none() is None:
            return candidate
        suffix += 1
        candidate = (base[:90] + "-" + str(suffix))[:100]


async def create_or_get_user(
    session: AsyncSession, identity: OAuthIdentity, *, now: datetime | None = None
) -> User:
    """Resolve a provider subject to its account, creating one on first login.

    Identity is never looked up by email. The same email at GitHub and Google
    therefore produces two accounts until a later explicit-link flow exists.
    """
    found = await session.execute(
        select(UserIdentity).where(
            UserIdentity.provider == identity.provider,
            UserIdentity.provider_subject == identity.subject,
        )
    )
    existing_identity = found.scalar_one_or_none()

    if existing_identity is not None:
        user = await session.get(User, existing_identity.user_id)
        if user is None or user.status != "active":
            raise AuthError("account-unavailable")
        # Profile data may change; the stable identity never does.
        if identity.avatar_url:
            user.avatar_url = identity.avatar_url
        if identity.email is not None:
            user.email = identity.email
            user.email_verified = bool(identity.email_verified)
        return user

    user = User(
        username=await _unique_username(session, identity),
        email=identity.email,
        email_verified=bool(identity.email and identity.email_verified),
        password_hash=None,
        status="active",
        provider=identity.provider,
        avatar_url=identity.avatar_url,
    )
    session.add(user)
    await session.flush()

    session.add(
        UserIdentity(
            user_id=user.id,
            provider=identity.provider,
            provider_subject=identity.subject,
        )
    )
    await session.flush()
    logger.info("created account %s from provider %s", user.id, identity.provider)
    return user


async def internal_guest_for_user(
    session: AsyncSession, user: User, *, now: datetime | None = None
) -> GuestSession:
    """The account's server-side ownership bridge.

    It has no usable browser token: the random token is hashed and discarded.
    Therefore no client can present it as a guest header; only the authenticated
    account session resolves to this row.
    """
    moment = _now(now)
    found = await session.execute(
        select(GuestSession).where(GuestSession.user_id == user.id)
    )
    guest = found.scalar_one_or_none()
    if guest is not None:
        if guest.revoked_at is not None or guest.expires_at <= moment:
            guest.revoked_at = None
            guest.expires_at = moment + INTERNAL_GUEST_TTL
        guest.last_seen_at = moment
        return guest

    token = guest_session.generate_token()
    guest = GuestSession(
        user_id=user.id,
        token_hash=guest_session.hash_token(token),
        created_at=moment,
        expires_at=moment + INTERNAL_GUEST_TTL,
        last_seen_at=moment,
        revoked_at=None,
    )
    session.add(guest)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent first login won the unique user_id race. Use its row.
        await session.rollback()
        found = await session.execute(
            select(GuestSession).where(GuestSession.user_id == user.id)
        )
        guest = found.scalar_one_or_none()
        if guest is None:
            raise
    return guest


async def issue_session(
    session: AsyncSession,
    user: User,
    settings: AuthSettings,
    *,
    now: datetime | None = None,
) -> tuple[UserSession, str]:
    moment = _now(now)
    token = secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)
    row = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=moment,
        expires_at=moment + timedelta(seconds=settings.session_ttl_seconds),
        last_seen_at=moment,
        revoked_at=None,
    )
    session.add(row)
    await session.flush()
    return row, token


async def user_for_session_token(
    session: AsyncSession,
    token: str | None,
    *,
    now: datetime | None = None,
) -> User | None:
    if token is None or token.strip() == "":
        return None
    moment = _now(now)
    found = await session.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == hash_token(token))
    )
    row = found.one_or_none()
    if row is None:
        return None
    account_session, user = row
    if account_session.revoked_at is not None or account_session.expires_at <= moment:
        return None
    if user.status != "active":
        return None
    return user


async def revoke_session(
    session: AsyncSession, token: str | None, *, now: datetime | None = None
) -> bool:
    if token is None or token.strip() == "":
        return False
    result = await session.execute(
        update(UserSession)
        .where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now(now))
    )
    return result.rowcount == 1


async def create_transaction(
    session: AsyncSession,
    *,
    state: str,
    provider: str,
    nonce: str | None,
    redirect_after: str | None,
    settings: AuthSettings,
    now: datetime | None = None,
) -> OAuthTransaction:
    moment = _now(now)
    row = OAuthTransaction(
        state_hash=hash_token(state),
        provider=provider,
        nonce=nonce,
        redirect_after=redirect_after,
        expires_at=moment + timedelta(seconds=settings.state_ttl_seconds),
        used_at=None,
    )
    session.add(row)
    await session.flush()
    return row


async def consume_transaction(
    session: AsyncSession,
    *,
    state: str,
    provider: str,
    now: datetime | None = None,
) -> OAuthTransaction:
    """Atomically consume a state row, or fail with one safe code."""
    moment = _now(now)
    result = await session.execute(
        update(OAuthTransaction)
        .where(
            OAuthTransaction.state_hash == hash_token(state),
            OAuthTransaction.provider == provider,
            OAuthTransaction.used_at.is_(None),
            OAuthTransaction.expires_at > moment,
        )
        .values(used_at=moment)
        .returning(OAuthTransaction)
    )
    transaction = result.scalar_one_or_none()
    if transaction is None:
        raise AuthError("state-invalid")
    # Consume before the provider exchange. A failed exchange cannot replay the
    # same state, even if the provider returns to the same callback URL.
    await session.commit()
    return transaction
