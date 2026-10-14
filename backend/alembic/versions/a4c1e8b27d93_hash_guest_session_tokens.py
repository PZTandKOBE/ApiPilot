"""hash guest session tokens

Phase 8.5 Step 2.  Three changes to `guest_sessions`, in the order that lets
existing rows survive them:

1. `token_hash` (SHA-256 hex of the token) and `revoked_at` arrive nullable;
2. every row that exists is migrated and then **invalidated** -- its digest is
   stored, it is marked revoked, and an expiry is filled in where the column was
   NULL.  The shared development token this project used in fixtures is a
   low-entropy, committed string, so it must not survive as a usable credential;
3. only then do the constraints go on (NOT NULL, unique) and the plaintext
   column come off.

Empty tables and populated tables take the same path: with no rows, step 2 is a
no-op and step 3 still applies.

**The downgrade is structurally complete and semantically lossy.**  It restores
the column, its NOT NULL and its unique constraint, filling it with per-row
placeholders that cannot authenticate anybody -- the plaintext was never stored,
so it cannot be brought back.  That is recorded in the Phase 8.5 Step 2 report as
the irreversible half of this migration.

Revision ID: a4c1e8b27d93
Revises: f3498529f573
Create Date: 2026-10-09 11:05:00.000000

"""
import hashlib
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4c1e8b27d93'
down_revision: Union[str, Sequence[str], None] = 'f3498529f573'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TOKEN_COLUMN = "session_token"
_HASH_COLUMN = "token_hash"
_HASH_LENGTH = 64
_TOKEN_LENGTH = 255


def _digest(token: str) -> str:
    """The same digest the service computes, inlined on purpose.

    A migration is a record of what happened at one point in time; importing the
    application's helper would make it change whenever that helper does.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def upgrade() -> None:
    """Add the digest and revocation, invalidate what exists, drop the plaintext."""
    op.add_column(
        "guest_sessions",
        sa.Column(
            _HASH_COLUMN,
            sa.String(length=_HASH_LENGTH),
            nullable=True,
            comment="SHA-256 hex digest of the session token; the token itself is never stored.",
        ),
    )
    op.add_column(
        "guest_sessions",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    connection = op.get_bind()
    now = datetime.now(timezone.utc)

    rows = connection.execute(
        sa.text(f"SELECT id, {_TOKEN_COLUMN}, expires_at FROM guest_sessions")
    ).fetchall()

    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE guest_sessions "
                f"SET {_HASH_COLUMN} = :digest, revoked_at = :now, "
                "expires_at = COALESCE(expires_at, :now) "
                "WHERE id = :id"
            ),
            {"digest": _digest(str(row[1])), "now": now, "id": row[0]},
        )

    if rows:
        print(f"    invalidated {len(rows)} pre-existing guest session(s)")

    # A row without a digest cannot satisfy the column below.  There is no such
    # row after the loop -- the plaintext column was NOT NULL -- but a table that
    # somehow held one would fail here rather than silently become unusable.
    remaining = connection.execute(
        sa.text(f"SELECT count(*) FROM guest_sessions WHERE {_HASH_COLUMN} IS NULL")
    ).scalar_one()

    if remaining:
        raise RuntimeError(
            f"{remaining} guest session(s) have no digest; refusing to continue"
        )

    op.alter_column(
        "guest_sessions",
        _HASH_COLUMN,
        existing_type=sa.String(length=_HASH_LENGTH),
        nullable=False,
    )
    op.alter_column(
        "guest_sessions",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_guest_sessions_token_hash", "guest_sessions", [_HASH_COLUMN]
    )

    op.drop_column("guest_sessions", _TOKEN_COLUMN)


def downgrade() -> None:
    """Restore the structure.  The plaintext cannot be restored; see the docstring."""
    op.add_column(
        "guest_sessions",
        sa.Column(_TOKEN_COLUMN, sa.String(length=_TOKEN_LENGTH), nullable=True),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"UPDATE guest_sessions SET {_TOKEN_COLUMN} = 'invalidated-' || id::text "
            f"WHERE {_TOKEN_COLUMN} IS NULL"
        )
    )

    op.alter_column(
        "guest_sessions",
        _TOKEN_COLUMN,
        existing_type=sa.String(length=_TOKEN_LENGTH),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_guest_sessions_session_token", "guest_sessions", [_TOKEN_COLUMN]
    )

    op.drop_constraint("uq_guest_sessions_token_hash", "guest_sessions", type_="unique")
    op.drop_column("guest_sessions", _HASH_COLUMN)
    op.drop_column("guest_sessions", "revoked_at")
    op.alter_column(
        "guest_sessions",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
