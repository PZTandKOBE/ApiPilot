"""add plan approval receipts to test_plans

Phase 8.6 Step 1.  An approval becomes a server-side fact instead of a client
claim: the row it approves records *who* approved, *when*, and *which content*
(`content_hash`, see `services/plan_hash.py`).  The fingerprint binds the
approval to the plan tree the executor will actually read, so a later content
change invalidates the receipt rather than silently keeping it.

Three nullable columns and five checks are enough; no new table, because a
plan has one current review state and its history lives in `test_runs` once
it runs.  The checks make the receipt self-consistent at the database level:

* approved requires exactly one actor and a content hash;
* the two actor columns are mutually exclusive;
* a rejected plan carries no approval credential at all.

Legacy data: before this revision no server-side path could set `approved`;
the only writer copied `plan.status` from the request body
(`services/runs.py` before this change).  Such rows are therefore *not*
receipts and are reset to `draft` -- a client-asserted approval must not
survive as if a human had made it.  Rows in `rejected` keep their rejection
metadata but lose any approval columns a client may have caused.

Revision ID: b1f2c3d4e5a6
Revises: 0a1b2c3d4e5f
Create Date: 2026-11-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b1f2c3d4e5a6"
down_revision: Union[str, Sequence[str], None] = "0a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the approval receipt and invalidate client-asserted approvals."""
    op.add_column(
        "test_plans",
        sa.Column("approved_by_guest_session_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "test_plans",
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "test_plans",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )

    op.create_index(
        op.f("ix_test_plans_approved_by_guest_session_id"),
        "test_plans",
        ["approved_by_guest_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_test_plans_approved_by_user_id"),
        "test_plans",
        ["approved_by_user_id"],
        unique=False,
    )

    # NO ACTION, not SET NULL: deleting an actor whose approved plans still
    # exist would otherwise null the receipt and break the checks below.  A
    # project deletion cascades through test_plans first, so the rows are gone
    # by the time the referenced user/guest row is checked.
    op.create_foreign_key(
        op.f("fk_test_plans_approved_by_guest_session_id_guest_sessions"),
        "test_plans",
        "guest_sessions",
        ["approved_by_guest_session_id"],
        ["id"],
        ondelete="NO ACTION",
    )
    op.create_foreign_key(
        op.f("fk_test_plans_approved_by_user_id_users"),
        "test_plans",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="NO ACTION",
    )

    # There was no server-side approval before this revision: the only writer
    # copied the client's plan.status into the new row.  Those rows cannot be
    # receipts, so they go back to draft; a reviewer has to approve again.
    op.execute(
        "UPDATE test_plans "
        "SET status = 'draft', approved_at = NULL "
        "WHERE status = 'approved'"
    )
    op.execute(
        "UPDATE test_plans "
        "SET approved_at = NULL, content_hash = NULL, "
        "    approved_by_guest_session_id = NULL, approved_by_user_id = NULL "
        "WHERE status = 'rejected'"
    )

    op.create_check_constraint(
        op.f("ck_test_plans_approval_actor_exclusive"),
        "test_plans",
        "approved_by_guest_session_id IS NULL OR approved_by_user_id IS NULL",
    )
    op.create_check_constraint(
        op.f("ck_test_plans_approval_actor_required"),
        "test_plans",
        "status <> 'approved' OR approved_by_guest_session_id IS NOT NULL "
        "OR approved_by_user_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_test_plans_approval_hash_required"),
        "test_plans",
        "status <> 'approved' OR content_hash IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_test_plans_approval_hash_length"),
        "test_plans",
        "content_hash IS NULL OR char_length(content_hash) = 64",
    )
    op.create_check_constraint(
        op.f("ck_test_plans_rejection_clears_approval"),
        "test_plans",
        "status <> 'rejected' OR (approved_at IS NULL AND content_hash IS NULL "
        "AND approved_by_guest_session_id IS NULL AND approved_by_user_id IS NULL)",
    )


def downgrade() -> None:
    """Drop the receipt.

    The data migration is not reversed: rows reset to draft stay draft, and no
    approval can be reconstructed.  That is recorded here rather than papered
    over with a fabricated timestamp.
    """
    op.drop_constraint(
        op.f("ck_test_plans_rejection_clears_approval"), "test_plans", type_="check"
    )
    op.drop_constraint(
        op.f("ck_test_plans_approval_hash_length"), "test_plans", type_="check"
    )
    op.drop_constraint(
        op.f("ck_test_plans_approval_hash_required"), "test_plans", type_="check"
    )
    op.drop_constraint(
        op.f("ck_test_plans_approval_actor_required"), "test_plans", type_="check"
    )
    op.drop_constraint(
        op.f("ck_test_plans_approval_actor_exclusive"), "test_plans", type_="check"
    )
    op.drop_constraint(
        op.f("fk_test_plans_approved_by_user_id_users"), "test_plans", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_test_plans_approved_by_guest_session_id_guest_sessions"),
        "test_plans",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_test_plans_approved_by_user_id"), table_name="test_plans")
    op.drop_index(
        op.f("ix_test_plans_approved_by_guest_session_id"), table_name="test_plans"
    )
    op.drop_column("test_plans", "content_hash")
    op.drop_column("test_plans", "approved_by_user_id")
    op.drop_column("test_plans", "approved_by_guest_session_id")
