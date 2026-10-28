"""Add Extract source snapshot fields to run_steps.

Revision ID: 0a1b2c3d4e5f
Revises: d4e5f6a7b8c9
Create Date: 2026-10-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Snapshot the Extract source on the run row.

    The plan row remains the authoring location; the run row is what the
    executor reads, so later plan edits cannot rewrite a past run's behaviour.
    Existing runs receive NULL and keep the legacy name-based Extract path.
    """
    op.add_column(
        "run_steps",
        sa.Column("source_path", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "run_steps",
        sa.Column("source_step_key", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_steps", "source_step_key")
    op.drop_column("run_steps", "source_path")
