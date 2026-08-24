"""add app_download_count and app_file_name to settings

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('settings', sa.Column('app_download_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('settings', sa.Column('app_file_name',      sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column('settings', 'app_file_name')
    op.drop_column('settings', 'app_download_count')
