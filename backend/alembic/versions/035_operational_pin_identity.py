"""Operational PIN identity and supervisor role.

Revision ID: 035_operational_pin_identity
Revises: 034_business_intelligence_v1
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "035_operational_pin_identity"
down_revision = "034_business_intelligence_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.alter_column("users", "email", existing_type=sa.String(), nullable=True)
    op.execute("UPDATE memberships SET role = 'SUPERVISOR' WHERE role = 'AUDITOR'")
    op.execute("""
        UPDATE role_profiles
        SET code = 'SUPERVISOR', name = 'Supervisor',
            description = 'Supervisão operacional da unidade sem administração de identidades ou contratos',
            updated_at = now()
        WHERE is_system = true AND code = 'AUDITOR'
    """)

    op.create_table(
        "operational_credentials",
        sa.Column("id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("store_id", uid, nullable=False),
        sa.Column("user_id", uid, nullable=False),
        sa.Column("membership_id", uid, nullable=False),
        sa.Column("employee_code", sa.String(length=20), nullable=False),
        sa.Column("pin_salt", sa.String(length=64), nullable=False),
        sa.Column("pin_hash", sa.String(length=128), nullable=False),
        sa.Column("pin_iterations", sa.Integer(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", name="uq_operational_credential_membership"),
        sa.UniqueConstraint("tenant_id", "store_id", "employee_code", name="uq_operational_employee_code"),
    )
    for column in ("tenant_id", "store_id", "user_id", "membership_id", "employee_code", "locked_until"):
        op.create_index(f"ix_operational_credentials_{column}", "operational_credentials", [column])
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
    op.execute("ALTER TABLE operational_credentials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operational_credentials FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY operational_credentials_isolation ON operational_credentials FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON operational_credentials TO dashem_runtime")

    permission = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("name", sa.String),
        sa.column("description", sa.Text), sa.column("capability_key", sa.String), sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(permission, [{
        "key": "operational.activate",
        "name": "Ativar identidade operacional",
        "description": "Troca a sessão administrativa autorizada por uma identidade operacional de código e PIN",
        "capability_key": None,
        "created_at": datetime.utcnow(),
    }])
    op.execute("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'operational.activate'
        FROM role_profiles rp
        WHERE rp.is_system = true AND rp.code IN ('OWNER','TENANT_OWNER','ADMIN','MANAGER')
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        DELETE FROM role_profile_permissions rpp
        USING role_profiles rp
        WHERE rpp.role_profile_id = rp.id AND rp.is_system = true AND rp.code = 'SUPERVISOR'
    """)
    op.execute("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), supervisor.id, manager_permissions.permission_key
        FROM role_profiles supervisor
        JOIN role_profiles manager ON manager.is_system = true AND manager.code = 'MANAGER'
        JOIN role_profile_permissions manager_permissions ON manager_permissions.role_profile_id = manager.id
        WHERE supervisor.is_system = true AND supervisor.code = 'SUPERVISOR'
          AND manager_permissions.permission_key NOT IN (
            'team.manage','permission.manage','tenant.settings','cash.configure',
            'device.configure','production.configure','channel.configure','provider.configure',
            'catalog.update','inventory.adjust','bi.refresh','operational.activate'
          )
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key = 'operational.activate'")
    op.execute("DELETE FROM permissions WHERE key = 'operational.activate'")
    op.drop_table("operational_credentials")
    op.execute("UPDATE memberships SET role = 'AUDITOR' WHERE role = 'SUPERVISOR'")
    op.execute("""
        UPDATE role_profiles
        SET code = 'AUDITOR', name = 'Auditor', description = 'Consulta operacional', updated_at = now()
        WHERE is_system = true AND code = 'SUPERVISOR'
    """)
    op.execute("UPDATE users SET email = 'operational-' || id::text || '@invalid.local' WHERE email IS NULL")
    op.alter_column("users", "email", existing_type=sa.String(), nullable=False)
