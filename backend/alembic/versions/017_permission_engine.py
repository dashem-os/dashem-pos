"""Canonical permissions, role profiles and contextual grants.

Revision ID: 017_permission_engine
Revises: 016_operational_observability
Create Date: 2026-08-23 16:10:00.000000
"""

from datetime import datetime
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "017_permission_engine"
down_revision: Union[str, None] = "016_operational_observability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = (
    ("catalog.read", "Consultar catálogo", "catalog"),
    ("catalog.update", "Administrar catálogo", "catalog"),
    ("inventory.read", "Consultar estoque", "inventory"),
    ("inventory.adjust", "Movimentar estoque", "inventory"),
    ("customer.read", "Consultar clientes", "customer"),
    ("customer.update", "Administrar clientes", "customer"),
    ("sale.read", "Consultar vendas", "counter_order"),
    ("sale.create", "Iniciar venda", "counter_order"),
    ("sale.item.update", "Alterar itens da venda", "counter_order"),
    ("sale.discount", "Aplicar desconto", "supervisor_override"),
    ("sale.cancel", "Cancelar venda", "supervisor_override"),
    ("sale.checkout", "Enviar venda ao pagamento", "counter_order"),
    ("cash.read", "Consultar caixa", "cash_management"),
    ("cash.configure", "Configurar terminais", "cash_management"),
    ("cash.open", "Abrir caixa", "cash_management"),
    ("cash.move", "Registrar sangria ou suprimento", "cash_management"),
    ("cash.close", "Fechar caixa", "cash_management"),
    ("payment.read", "Consultar pagamentos", "payments"),
    ("payment.create", "Criar pagamento", "payments"),
    ("payment.confirm", "Confirmar pagamento", "payments"),
    ("fiscal.read", "Consultar documento fiscal", "fiscal_nfce"),
    ("fiscal.issue", "Emitir documento fiscal", "fiscal_nfce"),
    ("fiscal.cancel", "Cancelar documento fiscal", "fiscal_nfce"),
    ("team.read", "Consultar equipe", None),
    ("team.manage", "Administrar equipe", None),
    ("permission.manage", "Administrar perfis e permissões", None),
    ("tenant.settings", "Administrar configurações do tenant", None),
    ("capability.read", "Consultar capacidades contratadas", None),
)

ROLE_PERMISSIONS = {
    "OWNER": "*",
    "TENANT_OWNER": "*",
    "ADMIN": "*",
    "MANAGER": tuple(key for key, _name, _capability in PERMISSIONS if key not in {"team.manage", "permission.manage", "tenant.settings", "cash.configure"}),
    "CASHIER": (
        "catalog.read", "inventory.read", "customer.read", "sale.read", "sale.create",
        "sale.item.update", "sale.discount", "sale.cancel", "sale.checkout",
        "cash.read", "cash.open", "cash.move", "cash.close",
        "payment.read", "payment.create", "payment.confirm",
        "fiscal.read", "fiscal.issue", "capability.read",
    ),
    "OPERATOR": (
        "catalog.read", "inventory.read", "customer.read", "sale.read", "sale.create",
        "sale.item.update", "sale.checkout", "payment.read",
        "payment.create", "payment.confirm", "fiscal.read", "fiscal.issue",
        "capability.read",
    ),
    "AUDITOR": (
        "catalog.read", "inventory.read", "customer.read", "sale.read", "cash.read",
        "payment.read", "fiscal.read", "team.read", "capability.read",
    ),
}


def _profile_id(code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"https://dashem.com/role-profile/{code}")


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("capability_key", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["capability_key"], ["capability_definitions.key"]),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_permissions_capability_key", "permissions", ["capability_key"])

    op.create_table(
        "role_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_role_profile_code"),
    )
    for column in ("tenant_id", "code", "is_system", "is_active"):
        op.create_index(f"ix_role_profiles_{column}", "role_profiles", [column])
    op.create_index(
        "uq_system_role_profile_code", "role_profiles", ["code"], unique=True,
        postgresql_where=sa.text("tenant_id IS NULL AND is_system = true"),
    )

    op.create_table(
        "role_profile_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_key", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["permission_key"], ["permissions.key"]),
        sa.ForeignKeyConstraint(["role_profile_id"], ["role_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_profile_id", "permission_key", name="uq_role_profile_permission"),
    )
    op.create_index("ix_role_profile_permissions_role_profile_id", "role_profile_permissions", ["role_profile_id"])
    op.create_index("ix_role_profile_permissions_permission_key", "role_profile_permissions", ["permission_key"])

    op.create_table(
        "membership_role_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_profile_id"], ["role_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "role_profile_id", name="uq_membership_role_profile"),
    )
    op.create_index("ix_membership_role_profiles_membership_id", "membership_role_profiles", ["membership_id"])
    op.create_index("ix_membership_role_profiles_role_profile_id", "membership_role_profiles", ["role_profile_id"])

    op.create_table(
        "permission_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_key", sa.String(length=100), nullable=False),
        sa.Column("effect", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_key"], ["permissions.key"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "permission_key", "store_id", name="uq_membership_permission_store_grant"),
    )
    for column in ("tenant_id", "store_id", "membership_id", "permission_key", "effect", "granted_by"):
        op.create_index(f"ix_permission_grants_{column}", "permission_grants", [column])

    now = datetime.utcnow()
    permission_table = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(permission_table, [
        {"key": key, "name": name, "description": name, "capability_key": capability, "created_at": now}
        for key, name, capability in PERMISSIONS
    ])
    profiles = sa.table(
        "role_profiles", sa.column("id", postgresql.UUID), sa.column("tenant_id", postgresql.UUID),
        sa.column("code", sa.String), sa.column("name", sa.String), sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean), sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(profiles, [
        {"id": _profile_id(role), "tenant_id": None, "code": role,
         "name": role.replace("_", " ").title(), "description": "Perfil canônico do Dashem.",
         "is_system": True, "is_active": True, "created_at": now, "updated_at": now}
        for role in ROLE_PERMISSIONS
    ])
    profile_permissions = sa.table(
        "role_profile_permissions", sa.column("id", postgresql.UUID),
        sa.column("role_profile_id", postgresql.UUID), sa.column("permission_key", sa.String),
    )
    all_keys = tuple(key for key, _name, _capability in PERMISSIONS)
    op.bulk_insert(profile_permissions, [
        {"id": uuid.uuid4(), "role_profile_id": _profile_id(role), "permission_key": permission}
        for role, assigned in ROLE_PERMISSIONS.items()
        for permission in (all_keys if assigned == "*" else assigned)
    ])

    # Preserve the product surface that existing tenants already used before
    # entitlements became an authorization gate. This is an explicit baseline
    # contract, not a runtime fallback; Control may later reduce it per contract.
    legacy_capabilities = (
        "catalog", "inventory", "customer", "cash_management", "payments",
        "counter_order", "supervisor_override", "fiscal_nfce", "barcode_scanning",
    )
    for capability in legacy_capabilities:
        op.execute(sa.text("""
            INSERT INTO tenant_capabilities
                (id, tenant_id, key, enabled, configuration, status, contract_limits, created_at, updated_at)
            SELECT gen_random_uuid(), t.id, :capability, true, '{}'::json, 'ACTIVE', '{}'::json, now(), now()
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM tenant_capabilities tc
                WHERE tc.tenant_id = t.id AND tc.key = :capability
            )
        """).bindparams(capability=capability))

    op.execute("GRANT SELECT ON permissions TO dashem_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON role_profiles, role_profile_permissions, membership_role_profiles, permission_grants TO dashem_runtime")

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "(store_id IS NULL OR nullif(current_setting('app.store_id', true), '') IS NULL OR store_id = nullif(current_setting('app.store_id', true), '')::uuid)"

    op.execute('ALTER TABLE role_profiles ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE role_profiles FORCE ROW LEVEL SECURITY')
    op.execute(f"CREATE POLICY role_profiles_read ON role_profiles FOR SELECT USING ({platform} OR tenant_id IS NULL OR {tenant})")
    op.execute(f"CREATE POLICY role_profiles_write ON role_profiles FOR ALL USING ({platform} OR {tenant}) WITH CHECK ({platform} OR ({tenant} AND tenant_id IS NOT NULL))")

    op.execute('ALTER TABLE permission_grants ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE permission_grants FORCE ROW LEVEL SECURITY')
    expression = f"({platform}) OR (({tenant}) AND ({store}))"
    op.execute(f"CREATE POLICY permission_grants_isolation ON permission_grants FOR ALL USING ({expression}) WITH CHECK ({expression})")

    for table, parent_expression in (
        ("role_profile_permissions", "EXISTS (SELECT 1 FROM role_profiles p WHERE p.id = role_profile_id)"),
        ("membership_role_profiles", "EXISTS (SELECT 1 FROM memberships m WHERE m.id = membership_id) AND EXISTS (SELECT 1 FROM role_profiles p WHERE p.id = role_profile_id)"),
    ):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY dashem_isolation ON "{table}" FOR ALL USING ({platform} OR ({parent_expression})) WITH CHECK ({platform} OR ({parent_expression}))')


def downgrade() -> None:
    op.drop_table("permission_grants")
    op.drop_table("membership_role_profiles")
    op.drop_table("role_profile_permissions")
    op.drop_table("role_profiles")
    op.drop_table("permissions")
