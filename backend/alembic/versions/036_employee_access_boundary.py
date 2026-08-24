"""Separate personnel records from authentication credentials.

Revision ID: 036_employee_access_boundary
Revises: 035_operational_pin_identity
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "036_employee_access_boundary"
down_revision = "035_operational_pin_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "employees",
        sa.Column("id", uid, nullable=False),
        sa.Column("tenant_id", uid, nullable=False),
        sa.Column("user_id", uid, nullable=True),
        sa.Column("home_store_id", uid, nullable=True),
        sa.Column("employee_number", sa.String(length=30), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("preferred_name", sa.String(length=100), nullable=True),
        sa.Column("tax_id", sa.String(length=11), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("job_title", sa.String(length=120), nullable=True),
        sa.Column("department", sa.String(length=120), nullable=True),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column("postal_code", sa.String(length=8), nullable=True),
        sa.Column("street", sa.String(length=200), nullable=True),
        sa.Column("street_number", sa.String(length=32), nullable=True),
        sa.Column("address_complement", sa.String(length=120), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("emergency_contact_name", sa.String(length=160), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["home_store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("tenant_id", "employee_number", name="uq_tenant_employee_number"),
        sa.UniqueConstraint("tenant_id", "tax_id", name="uq_tenant_employee_tax_id"),
    )
    for column in (
        "tenant_id", "user_id", "home_store_id", "employee_number", "full_name", "tax_id",
        "email", "phone", "job_title", "department", "hire_date", "status",
    ):
        op.create_index(f"ix_employees_{column}", "employees", [column])

    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    expression = f"({platform}) OR ({tenant})"
    op.execute("ALTER TABLE employees ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employees FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY employees_isolation ON employees FOR ALL USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON employees TO dashem_runtime")

    op.add_column("operational_credentials", sa.Column("employee_id", uid, nullable=True))
    op.execute("""
        INSERT INTO employees (
            id, tenant_id, user_id, home_store_id, employee_number, full_name, email,
            status, created_at, updated_at
        )
        SELECT DISTINCT ON (oc.user_id)
            gen_random_uuid(), oc.tenant_id, oc.user_id, oc.store_id,
            'LEG-' || substr(replace(oc.user_id::text, '-', ''), 1, 12),
            u.full_name, u.email, 'ACTIVE', now(), now()
        FROM operational_credentials oc
        JOIN users u ON u.id = oc.user_id
        ORDER BY oc.user_id, oc.created_at
    """)
    op.execute("""
        UPDATE operational_credentials oc
        SET employee_id = employee.id
        FROM employees employee
        WHERE employee.tenant_id = oc.tenant_id
          AND employee.user_id = oc.user_id
    """)
    op.alter_column("operational_credentials", "employee_id", nullable=False)
    op.create_foreign_key(
        "fk_operational_credentials_employee_id_employees",
        "operational_credentials", "employees", ["employee_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_operational_credentials_employee_id", "operational_credentials", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_operational_credentials_employee_id", table_name="operational_credentials")
    op.drop_constraint(
        "fk_operational_credentials_employee_id_employees",
        "operational_credentials", type_="foreignkey",
    )
    op.drop_column("operational_credentials", "employee_id")
    op.drop_table("employees")
