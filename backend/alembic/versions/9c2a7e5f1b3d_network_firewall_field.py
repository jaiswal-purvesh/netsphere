"""add firewall field to networks

Revision ID: 9c2a7e5f1b3d
Revises: 41e3e82c1344
Create Date: 2026-09-21 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '9c2a7e5f1b3d'
down_revision = '41e3e82c1344'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('networks', sa.Column('firewall', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('networks', 'firewall')
