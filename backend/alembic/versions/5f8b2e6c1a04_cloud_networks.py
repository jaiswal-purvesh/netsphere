"""Phase 3: Cloud Networks — cloud_network_interfaces, network_peerings

Revision ID: 5f8b2e6c1a04
Revises: 781cba56ba2f
Create Date: 2026-09-29 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '5f8b2e6c1a04'
down_revision = '781cba56ba2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cloud_network_interfaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('subnet_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('private_ip', sa.String(length=45), nullable=True),
        sa.Column('public_ip', sa.String(length=45), nullable=True),
        sa.Column('attached_to', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='in_use'),
        sa.Column('security_groups', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['subnet_id'], ['subnets.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_cloud_network_interfaces_subnet_id', 'cloud_network_interfaces', ['subnet_id'])
    op.create_index('ix_cloud_network_interfaces_external_id', 'cloud_network_interfaces', ['external_id'])

    op.create_table(
        'network_peerings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('network_a_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('network_b_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['network_a_id'], ['networks.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['network_b_id'], ['networks.id'], ondelete='CASCADE'),
        sa.CheckConstraint('network_a_id != network_b_id', name='ck_peerings_distinct_networks'),
        sa.UniqueConstraint('network_a_id', 'network_b_id', name='uq_peerings_pair'),
    )
    op.create_index('ix_network_peerings_network_a_id', 'network_peerings', ['network_a_id'])
    op.create_index('ix_network_peerings_network_b_id', 'network_peerings', ['network_b_id'])
    op.create_index('ix_network_peerings_external_id', 'network_peerings', ['external_id'])


def downgrade() -> None:
    op.drop_index('ix_network_peerings_external_id', table_name='network_peerings')
    op.drop_index('ix_network_peerings_network_b_id', table_name='network_peerings')
    op.drop_index('ix_network_peerings_network_a_id', table_name='network_peerings')
    op.drop_table('network_peerings')
    op.drop_index('ix_cloud_network_interfaces_external_id', table_name='cloud_network_interfaces')
    op.drop_index('ix_cloud_network_interfaces_subnet_id', table_name='cloud_network_interfaces')
    op.drop_table('cloud_network_interfaces')
