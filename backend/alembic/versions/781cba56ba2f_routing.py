"""Phase 3: Routing — route_tables, routes, subnets.route_table_id

Revision ID: 781cba56ba2f
Revises: b91e4d7a3c58
Create Date: 2026-09-29 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '781cba56ba2f'
down_revision = 'b91e4d7a3c58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'route_tables',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_main', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['network_id'], ['networks.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_route_tables_network_id', 'route_tables', ['network_id'])

    op.create_table(
        'routes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('route_table_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('destination_cidr', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_ref', sa.String(length=255), nullable=True),
        sa.Column('state', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['route_table_id'], ['route_tables.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "(CASE WHEN route_table_id IS NULL THEN 0 ELSE 1 END) "
            "+ (CASE WHEN device_id IS NULL THEN 0 ELSE 1 END) = 1",
            name='ck_routes_exactly_one_owner',
        ),
    )
    op.create_index('ix_routes_route_table_id', 'routes', ['route_table_id'])
    op.create_index('ix_routes_device_id', 'routes', ['device_id'])

    op.add_column('subnets', sa.Column('route_table_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_subnets_route_table_id', 'subnets', 'route_tables', ['route_table_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_subnets_route_table_id', 'subnets', type_='foreignkey')
    op.drop_column('subnets', 'route_table_id')
    op.drop_index('ix_routes_device_id', table_name='routes')
    op.drop_index('ix_routes_route_table_id', table_name='routes')
    op.drop_table('routes')
    op.drop_index('ix_route_tables_network_id', table_name='route_tables')
    op.drop_table('route_tables')
