"""reply approval, draft kind, forced password change

Revision ID: b7e4f2a9c1d3
Revises: 9f3d2c1ab0e4
Create Date: 2026-08-27 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e4f2a9c1d3'
down_revision = '9f3d2c1ab0e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default backfills existing rows so the NOT NULL adds succeed on
    # populated Postgres tables. Existing workspaces get require_reply_approval
    # = true: the safe default is to hold replies for review until an admin
    # opts into auto-send.
    op.add_column(
        'workspaces',
        sa.Column('require_reply_approval', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        'drafts',
        sa.Column('kind', sa.String(length=10), nullable=False,
                  server_default='outreach'),
    )


def downgrade() -> None:
    op.drop_column('drafts', 'kind')
    op.drop_column('users', 'must_change_password')
    op.drop_column('workspaces', 'require_reply_approval')
