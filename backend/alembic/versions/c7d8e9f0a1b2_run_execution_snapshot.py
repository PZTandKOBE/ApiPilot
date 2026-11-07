"""make run execution snapshots self-contained (historical runs stay v0)

Phase 8.7 Step 1.  A run used to snapshot most of the plan but re-read three
execution fields from the mutable plan tables at execution time:

* run_steps.produces, from test_steps.produces;
* run_steps.body / body_present, from test_steps.config.

This revision copies those fields onto run_steps for runs created from this
point on, and adds a compatibility mark to test_runs:

* snapshot_version = 1: every execution field was written by the create path;
* snapshot_version = 0: a historical run, whose execution content cannot be
  proven.  The executor refuses it (snapshot-unavailable) instead of falling
  back to the plan.

**No historical run is backfilled.**  Earlier drafts tried to prove a legacy
run's tree unchanged from test_steps.updated_at = test_steps.created_at.  That
proof is unsound: PostgreSQL now() is the transaction start time, so a step
inserted and updated inside one transaction keeps created_at = updated_at even
though its content changed.  There is no independent record of what a legacy
run executed (no run-level content hash, no audit trail), so every row that
exists before this revision is left at 0 and its new columns stay NULL/false.
A future candidate predicate, if one is ever added, must require:

* at least one run_scenario for the run;
* at least one run_step for every run_scenario;
* source_scenario_id / source_step_id / source_assertion_id present, pointing
  into the run's own plan, with matching stable keys and created_at not after
  the run;
* an independent content proof; timestamps alone are not one.

The old run rows keep their results, reports, assertions, evidence and events
untouched; only the new snapshot columns are added.  downgrade() drops those
columns and cannot restore a historical snapshot because none was ever stored.

Revision ID: c7d8e9f0a1b2
Revises: b1f2c3d4e5a6
Create Date: 2026-11-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b1f2c3d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the snapshot fields; mark every pre-existing run as v0."""
    op.add_column(
        "run_steps",
        sa.Column("produces", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "run_steps",
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "run_steps",
        sa.Column(
            "body_present",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "test_runs",
        sa.Column(
            "snapshot_version",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )

    # Every row that exists now predates this snapshot feature.  There is no
    # independent proof of what it executed, so none of them may run again.
    op.execute("UPDATE test_runs SET snapshot_version = 0")


def downgrade() -> None:
    """Drop the snapshot fields.

    The historical rows never stored these values, so there is nothing to
    restore; a downgrade only removes the columns.
    """
    op.drop_column("test_runs", "snapshot_version")
    op.drop_column("run_steps", "body_present")
    op.drop_column("run_steps", "body")
    op.drop_column("run_steps", "produces")
