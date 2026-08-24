"""Persist terminal authorization and operational sessions.

Revision ID: 042_operational_authority
Revises: 041_access_surfaces
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "042_operational_authority"
down_revision = "041_access_surfaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.add_column("operational_devices", sa.Column("authorization_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("operational_devices", sa.Column("authorized_at", sa.DateTime(), nullable=True))
    op.add_column("operational_devices", sa.Column("authorized_by", uid, nullable=True))
    op.add_column("operational_devices", sa.Column("authorization_expires_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_operational_devices_authorized_by_users", "operational_devices", "users", ["authorized_by"], ["id"])
    for column in ("authorized_at", "authorized_by", "authorization_expires_at"):
        op.create_index(f"ix_operational_devices_{column}", "operational_devices", [column])

    op.add_column("operational_credentials", sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "operational_sessions",
        sa.Column("id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("store_id", uid, nullable=False),
        sa.Column("register_id", uid, nullable=False),
        sa.Column("device_id", uid, nullable=False),
        sa.Column("user_id", uid, nullable=False),
        sa.Column("membership_id", uid, nullable=False),
        sa.Column("credential_id", uid, nullable=False),
        sa.Column("terminal_authorization_version", sa.Integer(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.ForeignKeyConstraint(["register_id"], ["registers.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["operational_devices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["credential_id"], ["operational_credentials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "tenant_id", "store_id", "register_id", "device_id", "user_id", "membership_id",
        "credential_id", "status", "started_at", "expires_at", "last_seen_at", "ended_at",
    ):
        op.create_index(f"ix_operational_sessions_{column}", "operational_sessions", [column])

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    store = "store_id = nullif(current_setting('app.store_id', true), '')::uuid"
    expression = f"({platform}) OR (({tenant}) AND (nullif(current_setting('app.store_id', true), '') IS NULL OR {store}))"
    op.execute("ALTER TABLE operational_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operational_sessions FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY operational_sessions_isolation ON operational_sessions FOR ALL USING ({expression}) WITH CHECK ({expression})")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON operational_sessions TO dashem_runtime")
    op.execute("""
        INSERT INTO permissions (key, name, description, capability_key, created_at)
        VALUES ('operational.session', 'Encerrar o próprio turno',
                'Permite ao colaborador encerrar a sessão operacional autenticada', NULL, now())
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), id, 'operational.session'
        FROM role_profiles
        WHERE is_system = true AND code IN ('SUPERVISOR', 'CASHIER', 'OPERATOR')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key = 'operational.session'")
    op.execute("DELETE FROM permissions WHERE key = 'operational.session'")
    op.drop_table("operational_sessions")
    op.drop_column("operational_credentials", "session_version")
    for column in ("authorization_expires_at", "authorized_by", "authorized_at"):
        op.drop_index(f"ix_operational_devices_{column}", table_name="operational_devices")
    op.drop_constraint("fk_operational_devices_authorized_by_users", "operational_devices", type_="foreignkey")
    for column in ("authorization_expires_at", "authorized_by", "authorized_at", "authorization_version"):
        op.drop_column("operational_devices", column)
