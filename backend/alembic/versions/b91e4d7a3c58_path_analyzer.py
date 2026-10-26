"""Phase 5: Path Analyzer — path_simulation_runs

Revision ID: b91e4d7a3c58
Revises: f3d8a6b12c47
Create Date: 2026-09-29 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b91e4d7a3c58'
down_revision = 'f3d8a6b12c47'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'path_simulation_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('destination', sa.String(length=64), nullable=False),
        sa.Column('protocol', sa.String(length=16), nullable=False),
        sa.Column('port_low', sa.Integer(), nullable=False),
        sa.Column('port_high', sa.Integer(), nullable=False),
        sa.Column('overall_verdict', sa.String(length=32), nullable=False),
        sa.Column('hops_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('notes_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('source_network_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('destination_network_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('triggered_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['source_network_id'], ['networks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['destination_network_id'], ['networks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['triggered_by_id'], ['users.id']),
    )
    op.create_index('ix_path_simulation_runs_created_at', 'path_simulation_runs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_path_simulation_runs_created_at', table_name='path_simulation_runs')
    op.drop_table('path_simulation_runs')
