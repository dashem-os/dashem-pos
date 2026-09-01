"""Give tenant commercial governance its own management destination.

Revision ID: 068_tenant_governance_nav
Revises: 067_storage_mib
"""

from alembic import op
import sqlalchemy as sa


revision = "068_tenant_governance_nav"
down_revision = "067_storage_mib"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (key, name, description, capability_key, created_at)
        VALUES (
            'contract.request',
            'Solicitar alteração contratual',
            'Permite solicitar ao Owner mudanças de atividade, capability ou quota.',
            NULL,
            now()
        )
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), profile.id, 'contract.request'
        FROM role_profiles profile
        WHERE profile.tenant_id IS NULL
          AND profile.is_system = true
          AND profile.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN')
          AND NOT EXISTS (
              SELECT 1 FROM role_profile_permissions assigned
              WHERE assigned.role_profile_id = profile.id
                AND assigned.permission_key = 'contract.request'
          )
        """
    )
    op.execute(
        sa.text(
            """
            INSERT INTO module_contributions (
                id, capability_key, surface, contribution_key, label, group_key,
                route, permission_key, implementation_key, sort_order,
                metadata_json, is_active
            )
            SELECT gen_random_uuid(), NULL, 'MANAGEMENT_NAV', 'subscription',
                   'Plano e solicitações', 'ADMINISTRAÇÃO', '/manage/subscription',
                   'management.read', 'subscription', 120, '{}'::json, true
            WHERE NOT EXISTS (
                SELECT 1 FROM module_contributions
                WHERE surface = 'MANAGEMENT_NAV'
                  AND contribution_key = 'subscription'
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM module_contributions "
        "WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'subscription'"
    )
    op.execute(
        "DELETE FROM role_profile_permissions "
        "WHERE permission_key = 'contract.request'"
    )
    op.execute(
        "DELETE FROM permission_grants "
        "WHERE permission_key = 'contract.request'"
    )
    op.execute("DELETE FROM permissions WHERE key = 'contract.request'")
