"""Align operational cash visibility and harden the audit trigger function.

Revision ID: 046_operational_role_alignment
Revises: 045_employee_pin_activation
"""

from alembic import op


revision = "046_operational_role_alignment"
down_revision = "045_employee_pin_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An operator may sell on a register already opened by a cashier, but may
    # not open, move or close cash. Without cash.read the POS always mistook an
    # existing session for a closed register.
    op.execute("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'cash.read'
        FROM role_profiles rp
        WHERE rp.is_system = true
          AND rp.code = 'OPERATOR'
          AND NOT EXISTS (
              SELECT 1
              FROM role_profile_permissions rpp
              WHERE rpp.role_profile_id = rp.id
                AND rpp.permission_key = 'cash.read'
          )
    """)

    # The function has no object dependency and therefore needs no mutable
    # schema lookup. This also resolves Supabase's search_path warning.
    op.execute("""
        ALTER FUNCTION public.dashem_reject_immutable_mutation()
        SET search_path = pg_catalog
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_profile_permissions rpp
        USING role_profiles rp
        WHERE rpp.role_profile_id = rp.id
          AND rp.is_system = true
          AND rp.code = 'OPERATOR'
          AND rpp.permission_key = 'cash.read'
    """)
    op.execute("""
        ALTER FUNCTION public.dashem_reject_immutable_mutation()
        RESET search_path
    """)
