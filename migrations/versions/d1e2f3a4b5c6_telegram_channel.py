"""Telegram conversational channel: prospect chat linkage.

Revision ID: d1e2f3a4b5c6
Revises: c9a1b2d3e4f5
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c9a1b2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prospects",
        sa.Column("telegram_chat_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_prospects_telegram_chat_id", "prospects", ["telegram_chat_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_prospects_telegram_chat_id", table_name="prospects")
    op.drop_column("prospects", "telegram_chat_id")
