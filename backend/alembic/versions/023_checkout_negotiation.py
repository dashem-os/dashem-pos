"""S8 checkout negotiation and payment allocations.

Revision ID: 023_checkout_negotiation
Revises: 022_table_service
Create Date: 2026-08-23 19:10:00.000000
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "023_checkout_negotiation"
down_revision: Union[str, None] = "022_table_service"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("checkout.read", "Consultar negociação de fechamento"),
    ("checkout.open", "Abrir negociação de fechamento"),
    ("checkout.payment", "Registrar e confirmar parcelas"),
    ("checkout.finalize", "Finalizar conta coberta"),
)


def upgrade() -> None:
    now = datetime.utcnow()
    uuid_type = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(14, 4)
    op.create_table(
        "checkout_negotiations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uuid_type, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("table_session_id", uuid_type, sa.ForeignKey("table_sessions.id"), nullable=True),
        sa.Column("sale_id", uuid_type, sa.ForeignKey("sales.id"), nullable=True),
        sa.Column("scope_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("subtotal", money, nullable=False),
        sa.Column("discount_total", money, nullable=False, server_default="0"),
        sa.Column("surcharge_total", money, nullable=False, server_default="0"),
        sa.Column("tax_total", money, nullable=False, server_default="0"),
        sa.Column("total_due", money, nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("opened_by", uuid_type, nullable=False),
        sa.Column("finalized_by", uuid_type, nullable=True),
        sa.Column("open_idempotency_key", sa.String(160), nullable=False),
        sa.Column("open_request_hash", sa.String(64), nullable=False),
        sa.Column("finalize_idempotency_key", sa.String(160), nullable=True),
        sa.Column("finalize_request_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "open_idempotency_key", name="uq_tenant_negotiation_open_key"),
        sa.CheckConstraint("version > 0", name="ck_negotiation_version_positive"),
        sa.CheckConstraint("total_due >= 0", name="ck_negotiation_total_nonnegative"),
    )
    for column in ("tenant_id", "store_id", "table_session_id", "sale_id", "scope_key", "status", "opened_by", "finalized_by", "open_idempotency_key", "finalize_idempotency_key", "created_at", "finalized_at"):
        op.create_index(f"ix_checkout_negotiations_{column}", "checkout_negotiations", [column])
    op.create_index(
        "uq_active_negotiation_scope", "checkout_negotiations",
        ["tenant_id", "store_id", "scope_key"], unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'PARTIALLY_COVERED', 'COVERED')"),
    )

    op.create_table(
        "negotiation_orders",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("negotiation_id", uuid_type, sa.ForeignKey("checkout_negotiations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("amount_snapshot", money, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("negotiation_id", "order_id", name="uq_negotiation_order"),
    )
    for column in ("tenant_id", "negotiation_id", "order_id", "created_at"):
        op.create_index(f"ix_negotiation_orders_{column}", "negotiation_orders", [column])

    op.create_table(
        "payment_intents",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uuid_type, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("negotiation_id", uuid_type, sa.ForeignKey("checkout_negotiations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cash_session_id", uuid_type, sa.ForeignKey("cash_sessions.id"), nullable=True),
        sa.Column("cash_movement_id", uuid_type, sa.ForeignKey("cash_movements.id"), nullable=True, unique=True),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("amount", money, nullable=False),
        sa.Column("tendered_amount", money, nullable=True),
        sa.Column("change_amount", money, nullable=False, server_default="0"),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("confirm_idempotency_key", sa.String(160), nullable=True),
        sa.Column("confirm_request_hash", sa.String(64), nullable=True),
        sa.Column("failure_idempotency_key", sa.String(160), nullable=True),
        sa.Column("failure_request_hash", sa.String(64), nullable=True),
        sa.Column("created_by", uuid_type, nullable=False),
        sa.Column("confirmed_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payment_intent_key"),
        sa.CheckConstraint("amount > 0", name="ck_payment_intent_amount_positive"),
    )
    for column in ("tenant_id", "store_id", "negotiation_id", "cash_session_id", "method", "status", "provider", "idempotency_key", "confirm_idempotency_key", "failure_idempotency_key", "created_by", "confirmed_by", "created_at", "confirmed_at", "failed_at"):
        op.create_index(f"ix_payment_intents_{column}", "payment_intents", [column])

    op.create_table(
        "payment_allocations",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("negotiation_id", uuid_type, sa.ForeignKey("checkout_negotiations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payment_intent_id", uuid_type, sa.ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", uuid_type, sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("order_item_id", uuid_type, sa.ForeignKey("order_items.id"), nullable=True),
        sa.Column("amount", money, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_allocation_amount_positive"),
    )
    for column in ("tenant_id", "negotiation_id", "payment_intent_id", "order_id", "order_item_id", "created_at"):
        op.create_index(f"ix_payment_allocations_{column}", "payment_allocations", [column])

    op.create_table(
        "negotiation_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("negotiation_id", uuid_type, sa.ForeignKey("checkout_negotiations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_id", uuid_type, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("tenant_id", "negotiation_id", "event_type", "actor_id", "created_at"):
        op.create_index(f"ix_negotiation_events_{column}", "negotiation_events", [column])

    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(permission_table, [{
        "key": key, "name": name, "description": name,
        "capability_key": "payments", "created_at": now,
    } for key, name in PERMISSIONS])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true
          AND p.key IN ('checkout.read', 'checkout.open', 'checkout.payment', 'checkout.finalize')
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'CASHIER', 'OPERATOR')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'checkout.read'
        FROM role_profiles rp WHERE rp.is_system = true AND rp.code = 'AUDITOR'
    """))

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    for table in ("checkout_negotiations", "payment_intents"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    for table in ("negotiation_orders", "payment_allocations", "negotiation_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        parent = (
            f"EXISTS (SELECT 1 FROM checkout_negotiations n WHERE n.id = negotiation_id "
            f"AND n.tenant_id = {table}.tenant_id AND (nullif(current_setting('app.store_id', true), '') IS NULL "
            "OR n.store_id = nullif(current_setting('app.store_id', true), '')::uuid))"
        )
        expression = f"({platform}) OR (({tenant}) AND ({parent}))"
        op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key LIKE 'checkout.%'")
    op.execute("DELETE FROM permissions WHERE key LIKE 'checkout.%'")
    op.drop_table("negotiation_events")
    op.drop_table("payment_allocations")
    op.drop_table("payment_intents")
    op.drop_index("uq_active_negotiation_scope", table_name="checkout_negotiations")
    op.drop_table("negotiation_orders")
    op.drop_table("checkout_negotiations")
