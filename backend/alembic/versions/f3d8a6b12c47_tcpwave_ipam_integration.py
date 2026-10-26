"""TCPWave IPAM integration: ipam_integrations, ipam_sync_runs,
provenance columns on networks/subnets/ip_addresses, ip_addresses unique
constraint

Revision ID: f3d8a6b12c47
Revises: a7c1f4e02b93
Create Date: 2026-09-29 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f3d8a6b12c47'
down_revision = 'a7c1f4e02b93'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ipam_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('vendor', sa.String(length=16), nullable=False, server_default='tcpwave'),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=True),
        sa.Column('port', sa.Integer(), nullable=False, server_default='7443'),
        sa.Column('verify_tls', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('auth_mode', sa.String(length=16), nullable=False, server_default='token'),
        sa.Column('token_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('token_last4', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('client_cert_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('client_key_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('organization_name', sa.String(length=255), nullable=True),
        sa.Column('cloud_account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_status', sa.String(length=16), nullable=True),
        sa.Column('last_test_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['cloud_account_id'], ['cloud_accounts.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
    )

    op.create_table(
        'ipam_sync_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('integration_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='ok'),
        sa.Column('error_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('networks_seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('networks_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('networks_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subnets_seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subnets_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('subnets_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ips_seen', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ips_created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ips_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('triggered_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['integration_id'], ['ipam_integrations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['triggered_by_id'], ['users.id']),
    )
    op.create_index('ix_ipam_sync_runs_integration_id', 'ipam_sync_runs', ['integration_id'])

    for table in ('networks', 'subnets', 'ip_addresses'):
        op.add_column(table, sa.Column('external_source', sa.String(length=32), nullable=True))
        op.add_column(table, sa.Column('external_ref', sa.String(length=255), nullable=True))
        op.add_column(table, sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True))
        op.create_index(f'ix_{table}_external_source', table, ['external_source'])

    op.add_column('ip_addresses', sa.Column('mac_address', sa.String(length=32), nullable=True))
    op.create_unique_constraint('uq_ip_addresses_subnet_ip', 'ip_addresses', ['subnet_id', 'ip_address'])


def downgrade() -> None:
    op.drop_constraint('uq_ip_addresses_subnet_ip', 'ip_addresses', type_='unique')
    op.drop_column('ip_addresses', 'mac_address')

    for table in ('networks', 'subnets', 'ip_addresses'):
        op.drop_index(f'ix_{table}_external_source', table_name=table)
        op.drop_column(table, 'last_synced_at')
        op.drop_column(table, 'external_ref')
        op.drop_column(table, 'external_source')

    op.drop_index('ix_ipam_sync_runs_integration_id', table_name='ipam_sync_runs')
    op.drop_table('ipam_sync_runs')
    op.drop_table('ipam_integrations')
