"""add last_user_id to broadcasts

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-05

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Последний обработанный users.id — чтобы продолжить рассылку после перезапуска
    op.add_column(
        'broadcasts',
        sa.Column('last_user_id', sa.Integer(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('broadcasts', 'last_user_id')
