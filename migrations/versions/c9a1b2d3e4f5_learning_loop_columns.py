"""learning loop: draft angle, evidence, judge dimensions, edit tracking

Revision ID: c9a1b2d3e4f5
Revises: b7e4f2a9c1d3
Create Date: 2026-08-27 01:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9a1b2d3e4f5'
down_revision = 'b7e4f2a9c1d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'drafts',
        sa.Column('angle', sa.String(length=200), nullable=False,
                  server_default=''),
    )
    op.add_column(
        'drafts',
        sa.Column('judge_scores', sa.JSON(), nullable=False,
                  server_default='{}'),
    )
    op.add_column(
        'drafts',
        sa.Column('grounding_notes', sa.Text(), nullable=False,
                  server_default=''),
    )
    op.add_column('drafts', sa.Column('edit_ratio', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('drafts', 'edit_ratio')
    op.drop_column('drafts', 'grounding_notes')
    op.drop_column('drafts', 'judge_scores')
    op.drop_column('drafts', 'angle')
