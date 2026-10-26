"""poa automation module

Revision ID: a1b2c3d4e5f6
Revises: 9c2a7e5f1b3d
Create Date: 2026-09-22 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a1b2c3d4e5f6'
down_revision = '9c2a7e5f1b3d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('poa_reference_files',
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('uploaded_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind'),
    )
    op.create_table('poa_runs',
    sa.Column('ritm_number', sa.String(length=64), nullable=False),
    sa.Column('input_filename', sa.String(length=255), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=False),
    sa.Column('manual_count', sa.Integer(), nullable=False),
    sa.Column('invalid_count', sa.Integer(), nullable=False),
    sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rows', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('excel_content', sa.LargeBinary(), nullable=False),
    sa.Column('docx_content', sa.LargeBinary(), nullable=False),
    sa.Column('created_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_poa_runs_ritm_number'), 'poa_runs', ['ritm_number'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_poa_runs_ritm_number'), table_name='poa_runs')
    op.drop_table('poa_runs')
    op.drop_table('poa_reference_files')
