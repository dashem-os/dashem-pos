"""S17 persisted business intelligence projections.

Revision ID: 034_business_intelligence_v1
Revises: 033_financial_reconciliation
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "034_business_intelligence_v1"
down_revision = "033_financial_reconciliation"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def _tenant_rls(table: str) -> None:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {table}_isolation ON {table} FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(14, 4)
    op.create_table(
        "bi_daily_facts",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False), sa.Column("competence_date", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False), sa.Column("register_key", sa.String(40), nullable=False),
        sa.Column("operator_key", sa.String(40), nullable=False), sa.Column("channel_key", sa.String(40), nullable=False),
        sa.Column("gross_revenue", money, nullable=False), sa.Column("net_revenue", money, nullable=False),
        sa.Column("discount_total", money, nullable=False), sa.Column("refunds_total", money, nullable=False),
        sa.Column("sales_count", sa.Integer(), nullable=False), sa.Column("confirmed_receipts", money, nullable=False),
        sa.Column("cash_receipts", money, nullable=False), sa.Column("pix_receipts", money, nullable=False),
        sa.Column("card_receipts", money, nullable=False), sa.Column("receivables_issued", money, nullable=False),
        sa.Column("receivables_settled", money, nullable=False), sa.Column("marketplace_settled", money, nullable=False),
        sa.Column("table_sessions_closed", sa.Integer(), nullable=False), sa.Column("table_service_seconds", sa.Integer(), nullable=False),
        sa.Column("production_tickets_completed", sa.Integer(), nullable=False), sa.Column("production_seconds", sa.Integer(), nullable=False),
        sa.Column("transfers_count", sa.Integer(), nullable=False), sa.Column("stockout_products", sa.Integer(), nullable=False),
        sa.Column("projected_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "store_id", "competence_date", "scope", "register_key", "operator_key", "channel_key", name="uq_bi_daily_fact_dimension"),
    )
    _indexes("bi_daily_facts", ("tenant_id", "store_id", "competence_date", "scope", "register_key", "operator_key", "channel_key", "projected_at"))
    _tenant_rls("bi_daily_facts")

    op.create_table(
        "bi_projection_states",
        sa.Column("id", uid, primary_key=True), sa.Column("tenant_id", uid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", uid, sa.ForeignKey("stores.id"), nullable=False), sa.Column("projection_key", sa.String(80), nullable=False),
        sa.Column("last_competence", sa.Date(), nullable=True), sa.Column("source_watermark", sa.DateTime(), nullable=True),
        sa.Column("projected_at", sa.DateTime(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False), sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "store_id", "projection_key", name="uq_bi_projection_state"),
    )
    _indexes("bi_projection_states", ("tenant_id", "store_id", "projection_key", "last_competence", "projected_at", "status"))
    _tenant_rls("bi_projection_states")

    permission = sa.table("permissions", sa.column("key", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime))
    now = datetime.utcnow()
    op.bulk_insert(permission, [
        {"key": "bi.read", "name": "Consultar BI", "description": "Consulta projeções gerenciais rastreáveis", "capability_key": None, "created_at": now},
        {"key": "bi.refresh", "name": "Atualizar BI", "description": "Reconstrói projeções sem alterar fatos transacionais", "capability_key": None, "created_at": now},
    ])
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key FROM role_profiles rp CROSS JOIN permissions p
        WHERE rp.is_system = true AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER','AUDITOR')
          AND p.key IN ('bi.read','bi.refresh')
    """))


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key IN ('bi.read','bi.refresh')")
    op.execute("DELETE FROM permissions WHERE key IN ('bi.read','bi.refresh')")
    op.drop_table("bi_projection_states")
    op.drop_table("bi_daily_facts")
