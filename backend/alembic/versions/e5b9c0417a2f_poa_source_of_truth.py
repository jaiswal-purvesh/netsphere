"""POA as source of truth: fw_poa_documents, richer fw_intents rule fields, fw_evidences

Revision ID: e5b9c0417a2f
Revises: d4a8f612e937
Create Date: 2026-09-23 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'e5b9c0417a2f'
down_revision = 'd4a8f612e937'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'fw_poa_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('poa_ref', sa.String(length=64), nullable=False),
        sa.Column('change_ref', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('snow_ticket', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('application_name', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('business_owner', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('technical_owner', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('environment', sa.String(length=16), nullable=False, server_default='prod'),
        sa.Column('source_application', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('destination_application', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('business_justification', sa.Text(), nullable=False, server_default=''),
        sa.Column('implementation_window', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('rollback_requirement', sa.Text(), nullable=False, server_default=''),
        sa.Column('source_format', sa.String(length=16), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('raw_content', sa.Text(), nullable=False, server_default=''),
        sa.Column('parse_warnings_json', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('rule_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('uploaded_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_fw_poa_documents_poa_ref', 'fw_poa_documents', ['poa_ref'])

    op.add_column('fw_intents', sa.Column('poa_document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_poa_documents.id', ondelete='CASCADE'), nullable=True))
    op.add_column('fw_intents', sa.Column('rule_id', sa.String(length=64), nullable=True))
    op.add_column('fw_intents', sa.Column('rule_name', sa.String(length=63), nullable=True))
    op.add_column('fw_intents', sa.Column('environment', sa.String(length=16), nullable=False, server_default='prod'))
    op.add_column('fw_intents', sa.Column('source_zone', sa.String(length=64), nullable=True))
    op.add_column('fw_intents', sa.Column('destination_zone', sa.String(length=64), nullable=True))
    op.add_column('fw_intents', sa.Column('nat_required', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('fw_intents', sa.Column('nat_details_json', postgresql.JSONB(), nullable=False, server_default='{}'))
    op.add_column('fw_intents', sa.Column('security_profile', sa.String(length=128), nullable=True))
    op.add_column('fw_intents', sa.Column('extra_fields_json', postgresql.JSONB(), nullable=False, server_default='{}'))
    op.create_index('ix_fw_intents_poa_document_id', 'fw_intents', ['poa_document_id'])
    op.create_index('ix_fw_intents_environment', 'fw_intents', ['environment'])

    op.create_table(
        'fw_evidences',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('intent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_intents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('fw_executions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rendered_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('snow_writeback_attempted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('snow_writeback_status', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('snow_writeback_detail', sa.Text(), nullable=False, server_default=''),
    )
    op.create_index('ix_fw_evidences_intent_id', 'fw_evidences', ['intent_id'])


def downgrade() -> None:
    op.drop_index('ix_fw_evidences_intent_id', table_name='fw_evidences')
    op.drop_table('fw_evidences')

    op.drop_index('ix_fw_intents_environment', table_name='fw_intents')
    op.drop_index('ix_fw_intents_poa_document_id', table_name='fw_intents')
    op.drop_column('fw_intents', 'extra_fields_json')
    op.drop_column('fw_intents', 'security_profile')
    op.drop_column('fw_intents', 'nat_details_json')
    op.drop_column('fw_intents', 'nat_required')
    op.drop_column('fw_intents', 'destination_zone')
    op.drop_column('fw_intents', 'source_zone')
    op.drop_column('fw_intents', 'environment')
    op.drop_column('fw_intents', 'rule_name')
    op.drop_column('fw_intents', 'rule_id')
    op.drop_column('fw_intents', 'poa_document_id')

    op.drop_index('ix_fw_poa_documents_poa_ref', table_name='fw_poa_documents')
    op.drop_table('fw_poa_documents')
