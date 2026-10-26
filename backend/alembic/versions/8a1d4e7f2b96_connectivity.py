"""Phase 8: Connectivity — circuits, bgp_sessions, connectivity_links, vpn_connections

Revision ID: 8a1d4e7f2b96
Revises: 5f8b2e6c1a04
Create Date: 2026-09-29 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '8a1d4e7f2b96'
down_revision = '5f8b2e6c1a04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'circuits',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cloud_account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('circuit_type', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('vrf', sa.String(length=128), nullable=True),
        sa.Column('bandwidth_mbps', sa.BigInteger(), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['cloud_account_id'], ['cloud_accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "(CASE WHEN cloud_account_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN device_id IS NULL THEN 0 ELSE 1 END) = 1",
            name='ck_circuits_exactly_one_owner',
        ),
    )
    op.create_index('ix_circuits_cloud_account_id', 'circuits', ['cloud_account_id'])
    op.create_index('ix_circuits_device_id', 'circuits', ['device_id'])
    op.create_index('ix_circuits_external_id', 'circuits', ['external_id'])

    op.create_table(
        'bgp_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('circuit_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('local_asn', sa.BigInteger(), nullable=False),
        sa.Column('peer_asn', sa.BigInteger(), nullable=False),
        sa.Column('local_ip', sa.String(length=45), nullable=True),
        sa.Column('peer_ip', sa.String(length=45), nullable=True),
        sa.Column('state', sa.String(length=16), nullable=False, server_default='established'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['circuit_id'], ['circuits.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_bgp_sessions_circuit_id', 'bgp_sessions', ['circuit_id'])
    op.create_index('ix_bgp_sessions_external_id', 'bgp_sessions', ['external_id'])

    op.create_table(
        'connectivity_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('circuit_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['network_id'], ['networks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['circuit_id'], ['circuits.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_connectivity_links_network_id', 'connectivity_links', ['network_id'])
    op.create_index('ix_connectivity_links_circuit_id', 'connectivity_links', ['circuit_id'])

    op.create_table(
        'vpn_connections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('peer_ip', sa.String(length=45), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='up'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['network_id'], ['networks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "(CASE WHEN network_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN device_id IS NULL THEN 0 ELSE 1 END) = 1",
            name='ck_vpn_connections_exactly_one_owner',
        ),
    )
    op.create_index('ix_vpn_connections_network_id', 'vpn_connections', ['network_id'])
    op.create_index('ix_vpn_connections_device_id', 'vpn_connections', ['device_id'])
    op.create_index('ix_vpn_connections_external_id', 'vpn_connections', ['external_id'])


def downgrade() -> None:
    op.drop_index('ix_vpn_connections_external_id', table_name='vpn_connections')
    op.drop_index('ix_vpn_connections_device_id', table_name='vpn_connections')
    op.drop_index('ix_vpn_connections_network_id', table_name='vpn_connections')
    op.drop_table('vpn_connections')
    op.drop_index('ix_connectivity_links_circuit_id', table_name='connectivity_links')
    op.drop_index('ix_connectivity_links_network_id', table_name='connectivity_links')
    op.drop_table('connectivity_links')
    op.drop_index('ix_bgp_sessions_external_id', table_name='bgp_sessions')
    op.drop_index('ix_bgp_sessions_circuit_id', table_name='bgp_sessions')
    op.drop_table('bgp_sessions')
    op.drop_index('ix_circuits_external_id', table_name='circuits')
    op.drop_index('ix_circuits_device_id', table_name='circuits')
    op.drop_index('ix_circuits_cloud_account_id', table_name='circuits')
    op.drop_table('circuits')
