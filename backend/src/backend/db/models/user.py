"""User system: ``users`` and ``guest_sessions``.

A project belongs to exactly one of these, never both -- see the XOR check
constraint in ``project.py``.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from backend.db.models.project import Project

__all__ = ["GuestSession", "User"]


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered account.

    ``password_hash`` is nullable because ``provider`` is not always ``email``:
    a GitHub or Google account has no password to store, and the frontend's
    ``AuthProvider`` union (``github`` | ``google`` | ``email``) makes those
    rows first-class rather than a special case.
    """

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
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


class GuestSession(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A browser's guest identity.

    The browser holds an opaque token; the database holds only its **SHA-256
    digest**.  Nothing here can be replayed from a stolen dump, and the raw
    token exists only in the response that issued it and in the browser that
    stored it -- the plaintext column this replaced was removed in Phase 8.5
    Step 2.

    Lifecycle, in one place:

    * every session has an expiry (30 days from issue, by the service's rule)
      -- NULL no longer means "never expires", because a session nobody can
      expire is a session nobody can reason about;
    * activity renews it, at most once per 24 hours, and that write is the
      service's job rather than this model's;
    * revocation ends a session immediately and permanently -- a revoked token
      cannot be renewed, and using it cannot revive it;
    * the projects a guest owns live in PostgreSQL like any other row, and this
      stage deliberately does not cascade them away when a session ends.
    """

    __tablename__ = "guest_sessions"

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
