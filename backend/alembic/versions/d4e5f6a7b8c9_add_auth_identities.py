"""add provider identities, account sessions and OAuth state

V1 auth keeps the existing guest identity untouched:

* users.email becomes nullable and non-unique (email is profile data, not an
  account key);
* user_identities is keyed by (provider, provider_subject);
* user_sessions stores only a hash of the HttpOnly application cookie;
* oauth_transactions makes the state value one-time and short-lived;
* guest_sessions.user_id links an account's internal ownership bridge to the
  existing project ownership model. Existing guest rows keep NULL.

Revision ID: d4e5f6a7b8c9
Revises: c33a1b2c3d4e
Create Date: 2026-10-18 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c33a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('uq_users_email', 'users', type_='unique')
    op.alter_column(
        'users',
        'email',
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )

    op.add_column(
        'guest_sessions',
        sa.Column('user_id', sa.UUID(), nullable=True, comment="Set only for an account's internal server-side identity."),
    )
    op.create_foreign_key(
        op.f('fk_guest_sessions_user_id_users'),
        'guest_sessions',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_unique_constraint(
        op.f('uq_guest_sessions_user_id'),
        'guest_sessions',
        ['user_id'],
    )
    op.create_index(
        op.f('ix_guest_sessions_user_id'),
        'guest_sessions',
        ['user_id'],
        unique=False,
    )

    op.create_table(
        'user_identities',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('provider_subject', sa.String(length=255), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name=op.f('fk_user_identities_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_user_identities')),
        sa.UniqueConstraint(
            'provider',
            'provider_subject',
            name='uq_user_identities_provider_subject',
        ),
    )
    op.create_index(
        op.f('ix_user_identities_user_id'),
        'user_identities',
        ['user_id'],
        unique=False,
    )

    op.create_table(
        'user_sessions',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False, comment='SHA-256 digest of the HttpOnly application session cookie.'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name=op.f('fk_user_sessions_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_user_sessions')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_user_sessions_token_hash')),
    )
    op.create_index(op.f('ix_user_sessions_user_id'), 'user_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_sessions_expires_at'), 'user_sessions', ['expires_at'], unique=False)

    op.create_table(
        'oauth_transactions',
        sa.Column('state_hash', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('nonce', sa.String(length=255), nullable=True),
        sa.Column('redirect_after', sa.String(length=500), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_transactions')),
        sa.UniqueConstraint('state_hash', name=op.f('uq_oauth_transactions_state_hash')),
    )
    op.create_index(op.f('ix_oauth_transactions_state_hash'), 'oauth_transactions', ['state_hash'], unique=False)
    op.create_index(op.f('ix_oauth_transactions_expires_at'), 'oauth_transactions', ['expires_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_oauth_transactions_expires_at'), table_name='oauth_transactions')
    op.drop_index(op.f('ix_oauth_transactions_state_hash'), table_name='oauth_transactions')
    op.drop_table('oauth_transactions')

    op.drop_index(op.f('ix_user_sessions_expires_at'), table_name='user_sessions')
    op.drop_index(op.f('ix_user_sessions_user_id'), table_name='user_sessions')
    op.drop_table('user_sessions')

    op.drop_index(op.f('ix_user_identities_user_id'), table_name='user_identities')
    op.drop_table('user_identities')

    op.drop_index(op.f('ix_guest_sessions_user_id'), table_name='guest_sessions')
    op.drop_constraint(op.f('uq_guest_sessions_user_id'), 'guest_sessions', type_='unique')
    op.drop_constraint(op.f('fk_guest_sessions_user_id_users'), 'guest_sessions', type_='foreignkey')
    op.drop_column('guest_sessions', 'user_id')

    op.drop_column('users', 'email_verified')
    op.alter_column(
        'users',
        'email',
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.create_unique_constraint('uq_users_email', 'users', ['email'])
