"""Hot-path indexes and wider daily counter channel.

- Composite indexes for the kill-switch and scheduler scans that run every
  minute (messages/suppressions by workspace+created_at, prospects by
  campaign+stage / campaign+next_followup_at).
- daily_counters.channel widened from 10 to 40 chars so it can also hold
  per-campaign queue buckets ("q:<campaign id>"), which make campaign
  daily_cap a true per-day cap.

Revision ID: 9f3d2c1ab0e4
Revises: 73ac718e2de0
Create Date: 2026-08-26
"""
import sqlalchemy as sa
from alembic import op

revision = '9f3d2c1ab0e4'
down_revision = '73ac718e2de0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_messages_ws_created', 'messages', ['workspace_id', 'created_at']
    )
    op.create_index(
        'ix_prospects_campaign_stage', 'prospects', ['campaign_id', 'stage']
    )
    op.create_index(
        'ix_prospects_followup', 'prospects', ['campaign_id', 'next_followup_at']
    )
    op.create_index(
        'ix_suppressions_ws_created', 'suppressions',
        ['workspace_id', 'created_at'],
    )
    with op.batch_alter_table('daily_counters') as batch:
        batch.alter_column(
            'channel',
            existing_type=sa.String(length=10),
            type_=sa.String(length=40),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('daily_counters') as batch:
        batch.alter_column(
            'channel',
            existing_type=sa.String(length=40),
            type_=sa.String(length=10),
            existing_nullable=False,
        )
    op.drop_index('ix_suppressions_ws_created', table_name='suppressions')
    op.drop_index('ix_prospects_followup', table_name='prospects')
    op.drop_index('ix_prospects_campaign_stage', table_name='prospects')
    op.drop_index('ix_messages_ws_created', table_name='messages')
