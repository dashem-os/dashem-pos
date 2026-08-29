"""Version plans and materialize audited SaaS contract discounts.

Revision ID: 056_owner_commercial_pricing
Revises: 055_saas_finance_projections
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "056_owner_commercial_pricing"
down_revision = "055_saas_finance_projections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    money = sa.Numeric(14, 2)

    op.add_column(
        "service_plans",
        sa.Column("capability_keys", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "service_plans", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.execute(
        """
        INSERT INTO service_plans (
            id, code, name, description, is_active, store_limit, user_limit,
            terminal_limit, storage_limit_mb, capability_keys, monthly_price,
            version, created_at, updated_at
        ) VALUES
        (gen_random_uuid(), 'DASHEM_ESSENCIAL', 'DASHEM Essencial',
         'Operação essencial de catálogo, caixa, pagamentos e balcão.', true,
         1, 5, 1, 1024,
         '["catalog","customer","cash_management","payments","counter_order"]'::json,
         119.00, 1, now(), now()),
        (gen_random_uuid(), 'DASHEM_PROFISSIONAL', 'DASHEM Profissional',
         'Operação completa de loja ou restaurante, com atendimento e produção.', true,
         1, 15, 3, 4096,
         '["catalog","inventory","customer","cash_management","payments","barcode_scanning","modifiers","combos","kitchen_routing","delivery_orders","counter_order","table_service","supervisor_override"]'::json,
         229.00, 1, now(), now()),
        (gen_random_uuid(), 'DASHEM_PERFORMANCE', 'DASHEM Performance',
         'Operação avançada, multiunidade e com controles comerciais ampliados.', true,
         3, 40, 10, 16384,
         '["catalog","inventory","customer","cash_management","payments","barcode_scanning","modifiers","combos","kitchen_routing","delivery_orders","counter_order","table_service","high_speed_checkout","supervisor_override","fiscal_nfce","receivables"]'::json,
         389.00, 1, now(), now()),
        (gen_random_uuid(), 'DASHEM_OMNICHANNEL', 'DASHEM Omnichannel',
         'Oferta futura condicionada ao Integration Hub e às homologações externas.', false,
         5, 75, 20, 32768,
         '["catalog","inventory","customer","cash_management","payments","barcode_scanning","modifiers","combos","kitchen_routing","delivery_orders","counter_order","table_service","high_speed_checkout","supervisor_override","fiscal_nfce","receivables"]'::json,
         649.00, 1, now(), now())
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.create_table(
        "service_plan_revisions",
        sa.Column("id", uid, nullable=False),
        sa.Column("plan_id", uid, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("store_limit", sa.Integer(), nullable=True),
        sa.Column("user_limit", sa.Integer(), nullable=True),
        sa.Column("terminal_limit", sa.Integer(), nullable=True),
        sa.Column("storage_limit_mb", sa.Integer(), nullable=True),
        sa.Column("capability_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("monthly_price", money, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", uid, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["plan_id"], ["service_plans.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "version", name="uq_service_plan_revision"),
        sa.CheckConstraint("version >= 1", name="ck_service_plan_revision_version_positive"),
    )
    op.create_index("ix_service_plan_revisions_plan_id", "service_plan_revisions", ["plan_id"])
    op.create_index("ix_service_plan_revisions_created_by", "service_plan_revisions", ["created_by"])
    op.create_index("ix_service_plan_revisions_created_at", "service_plan_revisions", ["created_at"])
    op.execute(
        """
        INSERT INTO service_plan_revisions (
            id, plan_id, version, code, name, description, is_active,
            store_limit, user_limit, terminal_limit, storage_limit_mb,
            capability_keys, monthly_price, reason, created_at
        )
        SELECT gen_random_uuid(), id, 1, code, name, description, is_active,
               store_limit, user_limit, terminal_limit, storage_limit_mb,
               capability_keys, monthly_price, 'Snapshot inicial migrado.', created_at
        FROM service_plans
        """
    )
    op.execute("GRANT SELECT, INSERT ON service_plan_revisions TO dashem_runtime")
    op.execute(
        "CREATE TRIGGER service_plan_revisions_immutable "
        "BEFORE UPDATE OR DELETE ON service_plan_revisions "
        "FOR EACH ROW EXECUTE FUNCTION dashem_reject_immutable_mutation()"
    )

    op.add_column("tenant_contracts", sa.Column("plan_revision_id", uid, nullable=True))
    op.create_foreign_key(
        "fk_tenant_contract_plan_revision",
        "tenant_contracts", "service_plan_revisions",
        ["plan_revision_id"], ["id"],
    )
    op.create_index("ix_tenant_contracts_plan_revision_id", "tenant_contracts", ["plan_revision_id"])
    op.execute(
        """
        UPDATE tenant_contracts AS contract
        SET plan_revision_id = revision.id
        FROM service_plan_revisions AS revision
        WHERE revision.plan_id = contract.plan_id AND revision.version = 1
        """
    )

    op.add_column("tenant_subscriptions", sa.Column("gross_monthly_amount", money, nullable=False, server_default="0"))
    op.add_column("tenant_subscriptions", sa.Column("discount_type", sa.String(20), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("discount_value", sa.Numeric(14, 4), nullable=False, server_default="0"))
    op.add_column("tenant_subscriptions", sa.Column("discount_amount", money, nullable=False, server_default="0"))
    op.add_column("tenant_subscriptions", sa.Column("discount_reason_code", sa.String(40), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("discount_reason", sa.Text(), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("discount_starts_on", sa.Date(), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("discount_ends_on", sa.Date(), nullable=True))
    op.add_column("tenant_subscriptions", sa.Column("discount_review_on", sa.Date(), nullable=True))
    op.execute("UPDATE tenant_subscriptions SET gross_monthly_amount = monthly_amount")
    op.create_check_constraint(
        "ck_tenant_subscriptions_commercial_amounts_nonnegative",
        "tenant_subscriptions",
        "gross_monthly_amount >= 0 AND discount_value >= 0 AND discount_amount >= 0",
    )
    op.create_check_constraint(
        "ck_tenant_subscriptions_discount_not_above_gross",
        "tenant_subscriptions", "discount_amount <= gross_monthly_amount",
    )
    op.create_check_constraint(
        "ck_tenant_subscriptions_net_formula",
        "tenant_subscriptions", "monthly_amount = gross_monthly_amount - discount_amount",
    )

    op.add_column("saas_finance_daily_metrics", sa.Column("gross_mrr", money, nullable=False, server_default="0"))
    op.add_column("saas_finance_daily_metrics", sa.Column("discount_mrr", money, nullable=False, server_default="0"))
    op.execute("UPDATE saas_finance_daily_metrics SET gross_mrr = contracted_mrr")
    op.add_column("saas_finance_subscription_snapshots", sa.Column("gross_mrr", money, nullable=False, server_default="0"))
    op.add_column("saas_finance_subscription_snapshots", sa.Column("discount_mrr", money, nullable=False, server_default="0"))
    op.execute("UPDATE saas_finance_subscription_snapshots SET gross_mrr = current_mrr")


def downgrade() -> None:
    op.drop_column("saas_finance_subscription_snapshots", "discount_mrr")
    op.drop_column("saas_finance_subscription_snapshots", "gross_mrr")
    op.drop_column("saas_finance_daily_metrics", "discount_mrr")
    op.drop_column("saas_finance_daily_metrics", "gross_mrr")

    op.drop_constraint("ck_tenant_subscriptions_net_formula", "tenant_subscriptions", type_="check")
    op.drop_constraint("ck_tenant_subscriptions_discount_not_above_gross", "tenant_subscriptions", type_="check")
    op.drop_constraint("ck_tenant_subscriptions_commercial_amounts_nonnegative", "tenant_subscriptions", type_="check")
    for column in (
        "discount_review_on", "discount_ends_on", "discount_starts_on", "discount_reason",
        "discount_reason_code", "discount_amount", "discount_value", "discount_type",
        "gross_monthly_amount",
    ):
        op.drop_column("tenant_subscriptions", column)

    op.drop_index("ix_tenant_contracts_plan_revision_id", table_name="tenant_contracts")
    op.drop_constraint("fk_tenant_contract_plan_revision", "tenant_contracts", type_="foreignkey")
    op.drop_column("tenant_contracts", "plan_revision_id")
    op.drop_table("service_plan_revisions")
    op.drop_column("service_plans", "version")
    op.drop_column("service_plans", "capability_keys")
