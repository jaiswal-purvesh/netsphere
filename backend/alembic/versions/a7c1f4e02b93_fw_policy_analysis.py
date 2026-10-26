"""Policy Optimizer: fw_policy_analysis_runs, fw_rule_records

Revision ID: a7c1f4e02b93
Revises: e5b9c0417a2f
Create Date: 2026-09-29 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'a7c1f4e02b93'
down_revision = 'e5b9c0417a2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fw_policy_analysis_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('integration_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_group', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='ok'),
        sa.Column('error_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('rule_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('severity_counts_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('findings_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('triggered_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['integration_id'], ['firewall_integrations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['triggered_by_id'], ['users.id']),
    )
    op.create_index('ix_fw_policy_analysis_runs_integration_id', 'fw_policy_analysis_runs', ['integration_id'])

    op.create_table(
        'fw_rule_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('integration_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_group', sa.String(length=128), nullable=True),
        sa.Column('rule_name', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False, server_default='allow'),
        sa.Column('disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('source_cidrs_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('destination_cidrs_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('services_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_findings_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('owner', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reviewed_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['integration_id'], ['firewall_integrations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['last_reviewed_by_id'], ['users.id']),
    )
    op.create_index(
        'ux_fw_rule_records_identity', 'fw_rule_records',
        ['integration_id', 'device_group', 'rule_name'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ux_fw_rule_records_identity', table_name='fw_rule_records')
    op.drop_table('fw_rule_records')
    op.drop_index('ix_fw_policy_analysis_runs_integration_id', table_name='fw_policy_analysis_runs')
    op.drop_table('fw_policy_analysis_runs')
