"""cloud integrations (AWS / Azure / GCP / OCI credential store)

Revision ID: c3e9a71f4d82
Revises: b7f4c2a91d05
Create Date: 2026-09-22 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'c3e9a71f4d82'
down_revision = 'b7f4c2a91d05'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cloud_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('vendor', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('account_identifier', sa.String(length=255), nullable=False),
        sa.Column('region_default', sa.String(length=64), nullable=True),
        sa.Column('credentials_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('credential_summary', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_status', sa.String(length=16), nullable=True),
        sa.Column('last_test_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.UniqueConstraint('vendor', 'account_identifier', name='uq_cloud_integration_vendor_account'),
    )
    op.create_index('ix_cloud_integrations_vendor', 'cloud_integrations', ['vendor'])


def downgrade() -> None:
    op.drop_index('ix_cloud_integrations_vendor', table_name='cloud_integrations')
    op.drop_table('cloud_integrations')
