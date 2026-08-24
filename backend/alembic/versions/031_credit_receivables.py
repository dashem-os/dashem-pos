"""S14 credit policy and receivable ledger.

Revision ID: 031_credit_receivables
Revises: 030_table_reservation_schedule
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "031_credit_receivables"
down_revision = "030_table_reservation_schedule"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def _tenant_rls(table: str, store_scoped: bool = True) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant})"
    if store_scoped:
        store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
        expression += f" AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store})"
    expression += ")"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    now = datetime.utcnow()
    # Counter/delivery Orders use a microsecond source version, which exceeds INTEGER.
    op.alter_column("checkout_negotiations", "source_version", type_=sa.BigInteger(), existing_type=sa.Integer())
    op.create_table(
        "customer_credit_policies",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", uid, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("credit_limit", sa.Numeric(14, 4), nullable=False),
        sa.Column("terms_days", sa.Integer(), nullable=False),
        sa.Column("allow_overdue", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("credit_limit >= 0", name="ck_credit_policy_limit_nonnegative"),
        sa.CheckConstraint("terms_days BETWEEN 0 AND 3650", name="ck_credit_policy_terms_range"),
        sa.CheckConstraint("version > 0", name="ck_credit_policy_version_positive"),
        sa.UniqueConstraint("tenant_id", "customer_id", name="uq_tenant_customer_credit_policy"),
    )
    _indexes("customer_credit_policies", ("tenant_id", "customer_id", "status", "updated_by", "created_at"))
    _tenant_rls("customer_credit_policies", False)

    op.create_table(
        "receivables",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("customer_id", uid, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("negotiation_id", uid, sa.ForeignKey("checkout_negotiations.id"), nullable=False),
        sa.Column("sale_id", uid, sa.ForeignKey("sales.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("principal_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("paid_amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("balance", sa.Numeric(14, 4), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("issue_idempotency_key", sa.String(160), nullable=False),
        sa.Column("issue_request_hash", sa.String(64), nullable=False),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", uid, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("principal_amount > 0", name="ck_receivable_principal_positive"),
        sa.CheckConstraint("paid_amount >= 0", name="ck_receivable_paid_nonnegative"),
        sa.CheckConstraint("balance >= 0", name="ck_receivable_balance_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_receivable_version_positive"),
        sa.UniqueConstraint("tenant_id", "issue_idempotency_key", name="uq_tenant_receivable_issue_key"),
    )
    _indexes("receivables", ("tenant_id", "store_id", "customer_id", "negotiation_id", "sale_id", "status", "issued_at", "due_at", "issue_idempotency_key", "reversed_at", "created_by"))
    _tenant_rls("receivables")

    op.create_table(
        "receivable_allocations",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("negotiation_id", uid, sa.ForeignKey("checkout_negotiations.id"), nullable=False),
        sa.Column("receivable_id", uid, sa.ForeignKey("receivables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_receivable_allocation_positive"),
        sa.UniqueConstraint("tenant_id", "negotiation_id", name="uq_tenant_negotiation_receivable_allocation"),
    )
    _indexes("receivable_allocations", ("tenant_id", "negotiation_id", "receivable_id", "created_at"))
    _tenant_rls("receivable_allocations", False)

    op.create_table(
        "receivable_ledger_entries",
        sa.Column("id", uid, primary_key=True),
        sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("receivable_id", uid, sa.ForeignKey("receivables.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 4), nullable=False),
        sa.Column("actor_id", uid, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("metadata_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount <> 0", name="ck_receivable_ledger_amount_nonzero"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_receivable_ledger_key"),
    )
    _indexes("receivable_ledger_entries", ("tenant_id", "store_id", "receivable_id", "entry_type", "actor_id", "idempotency_key", "created_at"))
    _tenant_rls("receivable_ledger_entries")

    capability = sa.table(
        "capability_definitions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("version", sa.String), sa.column("description", sa.Text), sa.column("scope", sa.String),
        sa.column("status", sa.String), sa.column("configuration_schema", postgresql.JSONB),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(capability, [{
        "key": "receivables", "name": "Crediário e contas a receber", "version": "1.0.0",
        "description": "Políticas de crédito, títulos, liquidação e cobrança.", "scope": "TENANT",
        "status": "ACTIVE", "configuration_schema": {}, "created_at": now, "updated_at": now,
    }])
    op.execute(sa.text("""
        INSERT INTO tenant_capabilities (id, tenant_id, key, enabled, status, contract_limits, configuration, created_at, updated_at)
        SELECT gen_random_uuid(), t.id, 'receivables', true, 'ACTIVE', '{}'::jsonb, '{}'::jsonb, now(), now()
        FROM tenants t
        WHERE NOT EXISTS (SELECT 1 FROM tenant_capabilities tc WHERE tc.tenant_id = t.id AND tc.key = 'receivables')
    """))
    permission = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime),
    )
    keys = (
        ("receivable.read", "Consultar contas a receber"),
        ("receivable.issue", "Emitir crédito em negociação"),
        ("receivable.reverse", "Estornar título a receber"),
        ("credit.policy.manage", "Administrar política de crédito"),
    )
    op.bulk_insert(permission, [{"key": k, "name": n, "description": n, "capability_key": "receivables", "created_at": now} for k, n in keys])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true
          AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER')
          AND p.key IN ('receivable.read','receivable.issue','receivable.reverse','credit.policy.manage')
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'receivable.read'
        FROM role_profiles rp WHERE rp.is_system = true AND rp.code = 'AUDITOR'
    """))


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('receivable.read','receivable.issue','receivable.reverse','credit.policy.manage')")
    op.execute("DELETE FROM permissions WHERE key IN ('receivable.read','receivable.issue','receivable.reverse','credit.policy.manage')")
    op.execute("DELETE FROM tenant_capabilities WHERE key = 'receivables'")
    op.execute("DELETE FROM capability_definitions WHERE key = 'receivables'")
    op.drop_table("receivable_ledger_entries")
    op.drop_table("receivable_allocations")
    op.drop_table("receivables")
    op.drop_table("customer_credit_policies")
    op.alter_column("checkout_negotiations", "source_version", type_=sa.Integer(), existing_type=sa.BigInteger())
