"""Cash & Payments Schema (POS-3)

Revision ID: 005_cash_payments
Revises: 004_sale_item_op_snapshot
Create Date: 2026-08-12 20:49:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '005_cash_payments'
down_revision: Union[str, None] = '004_sale_item_op_snapshot'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Registers
    op.create_table(
        'registers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'store_id', 'code', name='uq_tenant_store_register_code')
    )
    op.create_index(op.f('ix_registers_code'), 'registers', ['code'], unique=False)
    op.create_index(op.f('ix_registers_name'), 'registers', ['name'], unique=False)
    op.create_index(op.f('ix_registers_store_id'), 'registers', ['store_id'], unique=False)
    op.create_index(op.f('ix_registers_tenant_id'), 'registers', ['tenant_id'], unique=False)

    # Cash Sessions
    op.create_table(
        'cash_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('register_id', sa.UUID(), nullable=False),
        sa.Column('operator_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('opening_balance', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('closing_balance', sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column('opened_at', sa.DateTime(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['register_id'], ['registers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cash_sessions_opened_at'), 'cash_sessions', ['opened_at'], unique=False)
    op.create_index(op.f('ix_cash_sessions_operator_id'), 'cash_sessions', ['operator_id'], unique=False)
    op.create_index(op.f('ix_cash_sessions_register_id'), 'cash_sessions', ['register_id'], unique=False)
    op.create_index(op.f('ix_cash_sessions_status'), 'cash_sessions', ['status'], unique=False)
    op.create_index(op.f('ix_cash_sessions_store_id'), 'cash_sessions', ['store_id'], unique=False)
    op.create_index(op.f('ix_cash_sessions_tenant_id'), 'cash_sessions', ['tenant_id'], unique=False)

    # Cash Movements
    op.create_table(
        'cash_movements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('cash_session_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=False),
        sa.Column('movement_type', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['cash_session_id'], ['cash_sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cash_movements_actor_id'), 'cash_movements', ['actor_id'], unique=False)
    op.create_index(op.f('ix_cash_movements_cash_session_id'), 'cash_movements', ['cash_session_id'], unique=False)
    op.create_index(op.f('ix_cash_movements_created_at'), 'cash_movements', ['created_at'], unique=False)
    op.create_index(op.f('ix_cash_movements_movement_type'), 'cash_movements', ['movement_type'], unique=False)
    op.create_index(op.f('ix_cash_movements_store_id'), 'cash_movements', ['store_id'], unique=False)
    op.create_index(op.f('ix_cash_movements_tenant_id'), 'cash_movements', ['tenant_id'], unique=False)

    # Payments
    op.create_table(
        'payments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('sale_id', sa.UUID(), nullable=False),
        sa.Column('cash_session_id', sa.UUID(), nullable=True),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('transaction_ref', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['cash_session_id'], ['cash_sessions.id'], ),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payments_cash_session_id'), 'payments', ['cash_session_id'], unique=False)
    op.create_index(op.f('ix_payments_created_at'), 'payments', ['created_at'], unique=False)
    op.create_index(op.f('ix_payments_method'), 'payments', ['method'], unique=False)
    op.create_index(op.f('ix_payments_sale_id'), 'payments', ['sale_id'], unique=False)
    op.create_index(op.f('ix_payments_status'), 'payments', ['status'], unique=False)
    op.create_index(op.f('ix_payments_store_id'), 'payments', ['store_id'], unique=False)
    op.create_index(op.f('ix_payments_tenant_id'), 'payments', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_payments_transaction_ref'), 'payments', ['transaction_ref'], unique=False)

def downgrade() -> None:
    op.drop_table('payments')
    op.drop_table('cash_movements')
    op.drop_table('cash_sessions')
    op.drop_table('registers')
