"""add schedule_applied to links

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'links',
        sa.Column('schedule_applied', sa.Boolean(), server_default='false', nullable=False),
    )
    # Уже наступившие расписания считаем применёнными,
    # чтобы сразу после обновления бот ничего не переключил сам.
    op.execute("UPDATE links SET schedule_applied = true WHERE active_from <= now()")


def downgrade() -> None:
    op.drop_column('links', 'schedule_applied')
