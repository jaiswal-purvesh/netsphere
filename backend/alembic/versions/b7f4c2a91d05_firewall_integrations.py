"""firewall integrations (Panorama / FortiGate / PAN-OS credential store)

Revision ID: b7f4c2a91d05
Revises: a1b2c3d4e5f6
Create Date: 2026-09-22 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b7f4c2a91d05'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'firewall_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('vendor', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=True),
        sa.Column('port', sa.Integer(), nullable=False, server_default='443'),
        sa.Column('verify_tls', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('auth_type', sa.String(length=32), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('secret_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('secret_last4', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('device_group', sa.String(length=128), nullable=True),
        sa.Column('serial', sa.String(length=64), nullable=True),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('firewall_integrations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_status', sa.String(length=16), nullable=True),
        sa.Column('last_test_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_firewall_integrations_parent_id', 'firewall_integrations', ['parent_id'])
    op.create_index('ix_firewall_integrations_vendor', 'firewall_integrations', ['vendor'])


def downgrade() -> None:
    op.drop_index('ix_firewall_integrations_vendor', table_name='firewall_integrations')
    op.drop_index('ix_firewall_integrations_parent_id', table_name='firewall_integrations')
    op.drop_table('firewall_integrations')
