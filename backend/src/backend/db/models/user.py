"""User system: accounts, provider identities and browser guest sessions.

A project belongs to exactly one of these, never both -- see the XOR check
constraint in project.py.

V1 account rules:

* a provider identity is unique by (provider, provider_subject);
* an account can have several identities but they are never merged by email;
* the browser's guest token is separate from the server-side account session;
* account sessions store only a SHA-256 digest of a high-entropy cookie value.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.db.models.project import Project

__all__ = [
    "GuestSession",
    "OAuthTransaction",
    "User",
    "UserIdentity",
    "UserSession",
]


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered account.

    password_hash is nullable because V1 has no password authentication.
    Provider accounts have no password to store. email is nullable and not
    unique: a provider may not expose an email, and the same email at two
    providers must remain two accounts until an explicit link flow exists.
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'")
    )
    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="email", server_default=text("'email'")
    )
    avatar_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="owner_user",
        lazy="raise",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} username={self.username!r}>"


class UserIdentity(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One stable provider identity attached to an account.

    The unique key is the provider's stable subject, never email. A GitHub
    login and a Google login with the same email therefore produce two rows
    and two accounts; merging is a future, explicit flow.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_user_identities_provider_subject",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)

    def __repr__(self) -> str:
        return f"<UserIdentity provider={self.provider!r} subject={self.provider_subject!r}>"


class UserSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A server-side ApiPilot account session.

    The browser cookie contains a 256-bit random token; this row stores only
    its SHA-256 digest. Provider access tokens are never stored here.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="SHA-256 digest of the HttpOnly application session cookie.",
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<UserSession id={self.id!r} user_id={self.user_id!r}>"


class OAuthTransaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Short-lived, one-time OAuth state transaction.

    The raw state is in the provider URL; only its digest is stored. The
    callback consumes the row atomically before exchanging the code, so a
    replay finds used_at set even if the signed state cookie was copied.
    PKCE verifier and OIDC nonce live in the short-lived signed Authlib
    session cookie, not in this table.
    """

    __tablename__ = "oauth_transactions"
    __table_args__ = (
        UniqueConstraint(
            "state_hash",
            name="uq_oauth_transactions_state_hash",
        ),
    )

    state_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    nonce: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_after: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GuestSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A browser's guest identity, or a server-side account identity.

    The browser holds an opaque token; the database holds only its SHA-256
    digest. A row with user_id is the account's internal identity used to
    bridge the existing project-ownership model to a logged-in user; its
    token is random and is never returned to a browser. A row with a NULL
    user_id remains the self-hosted browser guest session.
    """

    __tablename__ = "guest_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uq_guest_sessions_user_id",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Set only for an account's internal server-side identity.",
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="SHA-256 hex digest of the session token; the token itself is never stored.",
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="guest_session",
        lazy="raise",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        """Never the token, never its digest -- an id and two timestamps."""
        return (
            f"<GuestSession id={self.id!r} expires_at={self.expires_at!r} "
            f"revoked_at={self.revoked_at!r}>"
        )
