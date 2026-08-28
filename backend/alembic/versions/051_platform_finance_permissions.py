"""Add granular platform finance permissions.

Revision ID: 051_platform_finance_permissions
Revises: 050_saas_finance_foundation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid


revision = "051_platform_finance_permissions"
down_revision = "050_saas_finance_foundation"
branch_labels = None
depends_on = None


FINANCE_PERMISSIONS = (
    ("control.finance.read", "Consultar Financeiro SaaS", "Consulta fatos financeiros e contratuais da plataforma."),
    ("control.finance.manage_billing", "Gerir conta de cobrança", "Mantém o cadastro fiscal e o contato de cobrança SaaS."),
    ("control.finance.collect", "Executar cobrança", "Executa comandos de cobrança SaaS quando o domínio existir."),
    ("control.finance.reconcile", "Conciliar recebimentos", "Concilia recebimentos SaaS confirmados pelo provedor."),
    ("control.finance.refund", "Estornar recebimentos", "Autoriza estornos financeiros SaaS de alto risco."),
    ("control.finance.export", "Exportar Financeiro SaaS", "Exporta fatos financeiros persistidos e autorizados."),
    ("control.finance.configure", "Configurar Financeiro SaaS", "Mantém parâmetros financeiros globais da plataforma."),
)


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "platform_permission_definitions",
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "platform_role_permissions",
        sa.Column("id", uid, nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("permission_key", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["permission_key"], ["platform_permission_definitions.key"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", "permission_key", name="uq_platform_role_permission"),
    )
    op.create_index("ix_platform_role_permissions_role", "platform_role_permissions", ["role"])
    op.create_index(
        "ix_platform_role_permissions_permission_key", "platform_role_permissions", ["permission_key"]
    )
    op.create_table(
        "platform_permission_grants",
        sa.Column("id", uid, nullable=False),
        sa.Column("platform_membership_id", uid, nullable=False),
        sa.Column("permission_key", sa.String(120), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", uid, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["platform_membership_id"], ["platform_memberships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_key"], ["platform_permission_definitions.key"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_membership_id", "permission_key",
            name="uq_platform_membership_permission_grant",
        ),
    )
    op.create_index(
        "ix_platform_permission_grants_platform_membership_id",
        "platform_permission_grants", ["platform_membership_id"],
    )
    op.create_index(
        "ix_platform_permission_grants_permission_key",
        "platform_permission_grants", ["permission_key"],
    )
    op.create_index(
        "ix_platform_permission_grants_granted_by",
        "platform_permission_grants", ["granted_by"],
    )

    permission_table = sa.table(
        "platform_permission_definitions",
        sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        permission_table,
        [
            {"key": key, "name": name, "description": description}
            for key, name, description in FINANCE_PERMISSIONS
        ],
    )

    role_permission_table = sa.table(
        "platform_role_permissions",
        sa.column("id", uid), sa.column("role", sa.String),
        sa.column("permission_key", sa.String),
    )
    owner_permissions = [permission[0] for permission in FINANCE_PERMISSIONS]
    admin_permissions = [
        "control.finance.read", "control.finance.manage_billing",
        "control.finance.collect", "control.finance.reconcile",
        "control.finance.export", "control.finance.configure",
    ]
    defaults = (
        [("PLATFORM_OWNER", key) for key in owner_permissions]
        + [("PLATFORM_ADMIN", key) for key in admin_permissions]
        + [("AUDITOR", "control.finance.read")]
    )
    op.bulk_insert(
        role_permission_table,
        [{"id": uuid.uuid4(), "role": role, "permission_key": key} for role, key in defaults],
    )

    for table in (
        "platform_permission_definitions",
        "platform_role_permissions",
        "platform_permission_grants",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_platform_only ON {table} FOR ALL "
            "USING (current_setting('app.platform_access', true) = 'true') "
            "WITH CHECK (current_setting('app.platform_access', true) = 'true')"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO dashem_runtime")


def downgrade() -> None:
    op.drop_table("platform_permission_grants")
    op.drop_table("platform_role_permissions")
    op.drop_table("platform_permission_definitions")
