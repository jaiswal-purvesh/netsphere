"""security policy — Phase 6: normalized security_groups/security_rules,
security_policy_batches (RITM intake), and fw_intents generalized to a
cloud target.

Revision ID: c4f8b2e6d915
Revises: 8a1d4e7f2b96
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'c4f8b2e6d915'
down_revision = '8a1d4e7f2b96'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'security_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('network_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('networks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cloud_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cloud_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(length=24), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
    )
    op.create_index('ix_security_groups_network_id', 'security_groups', ['network_id'])
    op.create_index('ix_security_groups_external_id', 'security_groups', ['external_id'])

    op.create_table(
        'security_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('security_group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('security_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('direction', sa.String(length=16), nullable=False, server_default='inbound'),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=8), nullable=False, server_default='allow'),
        sa.Column('protocol', sa.String(length=16), nullable=False, server_default='tcp'),
        sa.Column('port_low', sa.Integer(), nullable=True),
        sa.Column('port_high', sa.Integer(), nullable=True),
        sa.Column('cidr', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='manual'),
        sa.Column('managed_by_fwauto', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('rule_group_key', sa.String(length=64), nullable=True),
        sa.Column('ticket_ref', sa.String(length=64), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('extra_json', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index('ix_security_rules_security_group_id', 'security_rules', ['security_group_id'])
    op.create_index('ix_security_rules_rule_group_key', 'security_rules', ['rule_group_key'])
    op.create_index('ix_security_rules_external_id', 'security_rules', ['external_id'])

    op.create_table(
        'security_policy_batches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_filename', sa.String(length=255), nullable=True),
        sa.Column('source_format', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('ticket_ref', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('row_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('resolved_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unresolved_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unresolved_rows_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('parse_warnings_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('uploaded_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )

    # --- generalize fw_intents to a cloud target -----------------------
    op.alter_column('fw_intents', 'integration_id', nullable=True)
    op.add_column('fw_intents', sa.Column('target_kind', sa.String(length=24), nullable=False, server_default='firewall'))
    op.add_column('fw_intents', sa.Column('security_group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('security_groups.id', ondelete='CASCADE'), nullable=True))
    op.add_column('fw_intents', sa.Column('batch_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('security_policy_batches.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_fw_intents_security_group_id', 'fw_intents', ['security_group_id'])
    op.create_index('ix_fw_intents_batch_id', 'fw_intents', ['batch_id'])
    op.create_check_constraint(
        'ck_fw_intents_exactly_one_target', 'fw_intents',
        '(CASE WHEN integration_id IS NULL THEN 0 ELSE 1 END) '
        '+ (CASE WHEN security_group_id IS NULL THEN 0 ELSE 1 END) = 1',
    )


def downgrade() -> None:
    op.drop_constraint('ck_fw_intents_exactly_one_target', 'fw_intents', type_='check')
    op.drop_index('ix_fw_intents_batch_id', table_name='fw_intents')
    op.drop_index('ix_fw_intents_security_group_id', table_name='fw_intents')
    op.drop_column('fw_intents', 'batch_id')
    op.drop_column('fw_intents', 'security_group_id')
    op.drop_column('fw_intents', 'target_kind')
    op.alter_column('fw_intents', 'integration_id', nullable=False)

    op.drop_table('security_policy_batches')

    op.drop_index('ix_security_rules_external_id', table_name='security_rules')
    op.drop_index('ix_security_rules_rule_group_key', table_name='security_rules')
    op.drop_index('ix_security_rules_security_group_id', table_name='security_rules')
    op.drop_table('security_rules')

    op.drop_index('ix_security_groups_external_id', table_name='security_groups')
    op.drop_index('ix_security_groups_network_id', table_name='security_groups')
    op.drop_table('security_groups')
