"""add app fields to settings

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('settings', sa.Column('app_enabled',  sa.Boolean(),      server_default='false', nullable=False))
    op.add_column('settings', sa.Column('app_file_id',  sa.String(256),    nullable=True))
    op.add_column('settings', sa.Column('app_caption',  sa.Text(),         nullable=True))


def downgrade() -> None:
    op.drop_column('settings', 'app_caption')
    op.drop_column('settings', 'app_file_id')
    op.drop_column('settings', 'app_enabled')
