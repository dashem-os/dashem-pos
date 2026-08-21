"""Fiscal Gateway Schema (POS-4)

Revision ID: 007_fiscal_gateway
Revises: 006_pos3_amber_refinements
Create Date: 2026-08-12 21:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '007_fiscal_gateway'
down_revision: Union[str, None] = '006_pos3_amber_refinements'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Fiscal Documents
    op.create_table(
        'fiscal_documents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('sale_id', sa.UUID(), nullable=False),
        sa.Column('document_type', sa.String(), nullable=False, server_default='NFCE'),
        sa.Column('status', sa.String(), nullable=False, server_default='PENDING'),
        sa.Column('access_key', sa.String(), nullable=True),
        sa.Column('document_number', sa.Integer(), nullable=True),
        sa.Column('series', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('xml_content', sa.Text(), nullable=True),
        sa.Column('pdf_url', sa.String(), nullable=True),
        sa.Column('rejection_code', sa.String(), nullable=True),
        sa.Column('rejection_reason', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=False, server_default='FAKE_FISCAL_GATEWAY'),
        sa.Column('provider_document_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('issued_at', sa.DateTime(), nullable=True),
        sa.Column('canceled_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'access_key', name='uq_tenant_fiscal_access_key'),
        sa.UniqueConstraint('tenant_id', 'sale_id', name='uq_tenant_sale_fiscal_document')
    )
    op.create_index(op.f('ix_fiscal_documents_access_key'), 'fiscal_documents', ['access_key'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_created_at'), 'fiscal_documents', ['created_at'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_document_type'), 'fiscal_documents', ['document_type'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_provider'), 'fiscal_documents', ['provider'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_provider_document_id'), 'fiscal_documents', ['provider_document_id'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_sale_id'), 'fiscal_documents', ['sale_id'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_status'), 'fiscal_documents', ['status'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_store_id'), 'fiscal_documents', ['store_id'], unique=False)
    op.create_index(op.f('ix_fiscal_documents_tenant_id'), 'fiscal_documents', ['tenant_id'], unique=False)

    # Fiscal Events
    op.create_table(
        'fiscal_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('fiscal_document_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('details', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['fiscal_document_id'], ['fiscal_documents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fiscal_events_actor_id'), 'fiscal_events', ['actor_id'], unique=False)
    op.create_index(op.f('ix_fiscal_events_event_type'), 'fiscal_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_fiscal_events_fiscal_document_id'), 'fiscal_events', ['fiscal_document_id'], unique=False)
    op.create_index(op.f('ix_fiscal_events_store_id'), 'fiscal_events', ['store_id'], unique=False)
    op.create_index(op.f('ix_fiscal_events_tenant_id'), 'fiscal_events', ['tenant_id'], unique=False)

def downgrade() -> None:
    op.drop_table('fiscal_events')
    op.drop_table('fiscal_documents')
