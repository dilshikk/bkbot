"""add photo_file_id to links

Revision ID: a1b2c3d4e5f6
Revises: ed8ad7bf5e84
Create Date: 2026-07-30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'ed8ad7bf5e84'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'links',
        sa.Column('photo_file_id', sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('links', 'photo_file_id')
