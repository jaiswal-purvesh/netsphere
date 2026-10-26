"""firewall rule execution automation (Phase 3: intent/plan/PoA/approval/execution)

Revision ID: d4a8f612e937
Revises: c3e9a71f4d82
Create Date: 2026-09-22 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'd4a8f612e937'
down_revision = 'c3e9a71f4d82'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fw_intents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requester_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('ticket_ref', sa.String(length=64), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False, server_default=''),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('action', sa.String(length=8), nullable=False),
        sa.Column('logging', sa.String(length=16), nullable=False, server_default='session_end'),
        sa.Column('source_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('destination_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('service_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('integration_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('firewall_integrations.id'), nullable=False),
        sa.Column('device_group', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='received'),
        sa.Column('guardrail_findings_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('analysis_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_fw_intents_status', 'fw_intents', ['status'])

    op.create_table(
        'fw_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_intents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_hash', sa.String(length=64), nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('guardrail_findings_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('analysis_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('artifact_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('human_diff_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('device_config_version', sa.String(length=64), nullable=True),
        sa.Column('superseded', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_fw_plans_plan_hash', 'fw_plans', ['plan_hash'])
    op.create_index('ix_fw_plans_intent_id', 'fw_plans', ['intent_id'])

    op.create_table(
        'fw_poas',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('poa_revision', sa.String(length=64), nullable=False),
        sa.Column('template_version', sa.String(length=16), nullable=False, server_default='v1'),
        sa.Column('engineer_freetext_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('rendered_markdown', sa.Text(), nullable=False, server_default=''),
        sa.Column('signed_off_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('signed_off_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('superseded', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_fw_poas_poa_revision', 'fw_poas', ['poa_revision'])
    op.create_index('ix_fw_poas_plan_id', 'fw_poas', ['plan_id'])

    op.create_table(
        'fw_approvals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_intents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_plans.id'), nullable=False),
        sa.Column('plan_hash', sa.String(length=64), nullable=False),
        sa.Column('poa_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_poas.id'), nullable=False),
        sa.Column('poa_revision', sa.String(length=64), nullable=False),
        sa.Column('approver_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('decision', sa.String(length=16), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False, server_default=''),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_fw_approvals_intent_id', 'fw_approvals', ['intent_id'])

    op.create_table(
        'fw_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_intents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_plans.id'), nullable=False),
        sa.Column('executed_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('state', sa.String(length=24), nullable=False, server_default='started'),
        sa.Column('snapshot_ref', sa.String(length=128), nullable=True),
        sa.Column('commit_job_id', sa.String(length=64), nullable=True),
        sa.Column('push_job_id', sa.String(length=64), nullable=True),
        sa.Column('preview_matched', sa.Boolean(), nullable=True),
        sa.Column('verify_result_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('rolled_back', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_fw_executions_intent_id', 'fw_executions', ['intent_id'])


def downgrade() -> None:
    op.drop_index('ix_fw_executions_intent_id', table_name='fw_executions')
    op.drop_table('fw_executions')
    op.drop_index('ix_fw_approvals_intent_id', table_name='fw_approvals')
    op.drop_table('fw_approvals')
    op.drop_index('ix_fw_poas_plan_id', table_name='fw_poas')
    op.drop_index('ix_fw_poas_poa_revision', table_name='fw_poas')
    op.drop_table('fw_poas')
    op.drop_index('ix_fw_plans_intent_id', table_name='fw_plans')
    op.drop_index('ix_fw_plans_plan_hash', table_name='fw_plans')
    op.drop_table('fw_plans')
    op.drop_index('ix_fw_intents_status', table_name='fw_intents')
    op.drop_table('fw_intents')
