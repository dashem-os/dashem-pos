"""Table reservation schedule and operational permission boundary.

Revision ID: 030_table_reservation_schedule
Revises: 029_tenant_backoffice
"""

from alembic import op
import sqlalchemy as sa


revision = "030_table_reservation_schedule"
down_revision = "029_tenant_backoffice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "table_reservations",
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="120"),
    )
    op.create_check_constraint(
        "ck_table_reservation_duration_range",
        "table_reservations",
        "duration_minutes BETWEEN 15 AND 1440",
    )
    op.alter_column("table_reservations", "duration_minutes", server_default=None)
    op.execute(sa.text("""
        DELETE FROM role_profile_permissions rpp
        USING role_profiles rp
        WHERE rpp.role_profile_id = rp.id
          AND rp.is_system = true
          AND rp.code IN ('CASHIER', 'OPERATOR')
          AND rpp.permission_key = 'table.reservation.manage'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'table.reservation.manage'
        FROM role_profiles rp
        WHERE rp.is_system = true
          AND rp.code IN ('CASHIER', 'OPERATOR')
          AND NOT EXISTS (
              SELECT 1 FROM role_profile_permissions rpp
              WHERE rpp.role_profile_id = rp.id
                AND rpp.permission_key = 'table.reservation.manage'
          )
    """))
    op.drop_constraint(
        "ck_table_reservation_duration_range",
        "table_reservations",
        type_="check",
    )
    op.drop_column("table_reservations", "duration_minutes")
