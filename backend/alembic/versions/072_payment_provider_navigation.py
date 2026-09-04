"""Expose payment provider configuration in tenant management.

Revision ID: 072_payment_provider_nav
Revises: 071_terminal_credential_throttle
"""

from alembic import op


revision = "072_payment_provider_nav"
down_revision = "071_terminal_credential_throttle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO module_contributions (
            id, capability_key, surface, contribution_key, label, group_key,
            route, permission_key, implementation_key, sort_order,
            metadata_json, is_active
        )
        SELECT gen_random_uuid(), 'tef', 'MANAGEMENT_NAV', 'payment_providers',
               'Provedores de pagamento', 'ADMINISTRAÇÃO', '/manage/payment_providers',
               'provider.read', 'payment_providers', 115, '{}'::json, true
        WHERE NOT EXISTS (
            SELECT 1 FROM module_contributions
            WHERE surface = 'MANAGEMENT_NAV'
              AND contribution_key = 'payment_providers'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM module_contributions "
        "WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'payment_providers'"
    )
