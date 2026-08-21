"""POS-3 AMBER Refinements (Variance, Overpayment, Event ID)

Revision ID: 006_pos3_amber_refinements
Revises: 005_cash_payments
Create Date: 2026-08-12 20:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '006_pos3_amber_refinements'
down_revision: Union[str, None] = '005_cash_payments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Cash Sessions Variance
    op.add_column('cash_sessions', sa.Column('expected_balance', sa.Numeric(precision=14, scale=4), nullable=True))
    op.add_column('cash_sessions', sa.Column('variance', sa.Numeric(precision=14, scale=4), nullable=True))

    # Payments Tendered, Change, Provider Event ID
    op.add_column('payments', sa.Column('tendered_amount', sa.Numeric(precision=14, scale=4), nullable=True))
    op.add_column('payments', sa.Column('change_amount', sa.Numeric(precision=14, scale=4), nullable=True))
    op.add_column('payments', sa.Column('provider', sa.String(), nullable=False, server_default='FAKE_PSP'))
    op.add_column('payments', sa.Column('provider_event_id', sa.String(), nullable=True))

    op.create_index(op.f('ix_payments_provider'), 'payments', ['provider'], unique=False)
    op.create_index(op.f('ix_payments_provider_event_id'), 'payments', ['provider_event_id'], unique=False)
    op.create_unique_constraint('uq_tenant_provider_event_id', 'payments', ['tenant_id', 'provider', 'provider_event_id'])

def downgrade() -> None:
    op.drop_constraint('uq_tenant_provider_event_id', 'payments', type_='unique')
    op.drop_index(op.f('ix_payments_provider_event_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_provider'), table_name='payments')
    op.drop_column('payments', 'provider_event_id')
    op.drop_column('payments', 'provider')
    op.drop_column('payments', 'change_amount')
    op.drop_column('payments', 'tendered_amount')
    op.drop_column('cash_sessions', 'variance')
    op.drop_column('cash_sessions', 'expected_balance')
