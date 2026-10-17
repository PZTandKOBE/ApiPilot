"""create run reports

C33-R1: one immutable PDF report per generation, stored with its bytes so the
metadata row and the file cannot disagree.

Revision ID: c33a1b2c3d4e
Revises: a4c1e8b27d93
Create Date: 2026-10-17 21:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c33a1b2c3d4e'
down_revision: Union[str, Sequence[str], None] = 'a4c1e8b27d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'run_reports',
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), server_default='application/pdf', nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('byte_size > 0', name=op.f('ck_run_reports_byte_size_positive')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_run_reports_project_id_projects'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['test_runs.id'], name=op.f('fk_run_reports_run_id_test_runs'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_run_reports')),
    )
    op.create_index(op.f('ix_run_reports_project_id'), 'run_reports', ['project_id'], unique=False)
    op.create_index(op.f('ix_run_reports_run_id'), 'run_reports', ['run_id'], unique=False)
    op.create_index('ix_run_reports_project_created_at', 'run_reports', ['project_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_run_reports_project_created_at', table_name='run_reports')
    op.drop_index(op.f('ix_run_reports_run_id'), table_name='run_reports')
    op.drop_index(op.f('ix_run_reports_project_id'), table_name='run_reports')
    op.drop_table('run_reports')
