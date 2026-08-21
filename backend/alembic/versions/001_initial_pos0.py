"""Initial POS-0 Schema

Revision ID: 001_initial_pos0
Revises: 
Create Date: 2026-08-12 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = '001_initial_pos0'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Tenants
    op.create_table(
        'tenants',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tenants_name'), 'tenants', ['name'], unique=False)
    op.create_index(op.f('ix_tenants_slug'), 'tenants', ['slug'], unique=True)

    # Stores
    op.create_table(
        'stores',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stores_code'), 'stores', ['code'], unique=False)
    op.create_index(op.f('ix_stores_name'), 'stores', ['name'], unique=False)
    op.create_index(op.f('ix_stores_tenant_id'), 'stores', ['tenant_id'], unique=False)

    # Users
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Memberships
    op.create_table(
        'memberships',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'tenant_id', 'store_id', name='uq_user_tenant_store')
    )
    op.create_index(op.f('ix_memberships_store_id'), 'memberships', ['store_id'], unique=False)
    op.create_index(op.f('ix_memberships_tenant_id'), 'memberships', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)

    # Outbox Events
    op.create_table(
        'outbox_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('aggregate_type', sa.String(), nullable=False),
        sa.Column('aggregate_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('correlation_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbox_events_aggregate_id'), 'outbox_events', ['aggregate_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_aggregate_type'), 'outbox_events', ['aggregate_type'], unique=False)
    op.create_index(op.f('ix_outbox_events_available_at'), 'outbox_events', ['available_at'], unique=False)
    op.create_index(op.f('ix_outbox_events_correlation_id'), 'outbox_events', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_created_at'), 'outbox_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_outbox_events_event_type'), 'outbox_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_outbox_events_status'), 'outbox_events', ['status'], unique=False)
    op.create_index(op.f('ix_outbox_events_tenant_id'), 'outbox_events', ['tenant_id'], unique=False)

    # Audit Events
    op.create_table(
        'audit_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('payload', sa.String(), nullable=False),
        sa.Column('correlation_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_action'), 'audit_events', ['action'], unique=False)
    op.create_index(op.f('ix_audit_events_actor_id'), 'audit_events', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_events_correlation_id'), 'audit_events', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_audit_events_store_id'), 'audit_events', ['store_id'], unique=False)
    op.create_index(op.f('ix_audit_events_target'), 'audit_events', ['target'], unique=False)
    op.create_index(op.f('ix_audit_events_tenant_id'), 'audit_events', ['tenant_id'], unique=False)

    # Idempotency Records
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=False),
        sa.Column('operation', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('request_hash', sa.String(), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_body', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'actor_id', 'operation', 'idempotency_key', name='uq_tenant_actor_op_key')
    )
    op.create_index(op.f('ix_idempotency_records_actor_id'), 'idempotency_records', ['actor_id'], unique=False)
    op.create_index(op.f('ix_idempotency_records_idempotency_key'), 'idempotency_records', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_idempotency_records_operation'), 'idempotency_records', ['operation'], unique=False)
    op.create_index(op.f('ix_idempotency_records_request_hash'), 'idempotency_records', ['request_hash'], unique=False)
    op.create_index(op.f('ix_idempotency_records_tenant_id'), 'idempotency_records', ['tenant_id'], unique=False)

def downgrade() -> None:
    op.drop_table('idempotency_records')
    op.drop_table('audit_events')
    op.drop_table('outbox_events')
    op.drop_table('memberships')
    op.drop_table('users')
    op.drop_table('stores')
    op.drop_table('tenants')
