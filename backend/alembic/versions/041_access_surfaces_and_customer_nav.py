"""Separate management, operational and device access surfaces.

Revision ID: 041_access_surfaces
Revises: 040_commercial_pilot
"""
from alembic import op
import sqlalchemy as sa


revision = "041_access_surfaces"
down_revision = "040_commercial_pilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO module_contributions
          (id, capability_key, surface, contribution_key, label, group_key, route,
           permission_key, implementation_key, sort_order, metadata_json, is_active)
        SELECT gen_random_uuid(), 'customer', 'MANAGEMENT_NAV', 'customers', 'Clientes',
               'RELACIONAMENTO', '/manage/customers', 'customer.read', 'customers', 85, '{}'::json, true
        WHERE NOT EXISTS (
          SELECT 1 FROM module_contributions
          WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'customers'
        )
    """))
    op.execute(sa.text("""
        UPDATE module_contributions SET label = 'Funcionários e acessos', group_key = 'PESSOAS'
        WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'team'
    """))
    op.execute(sa.text("""
        UPDATE module_contributions SET label = 'Terminais e dispositivos'
        WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'devices'
    """))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM module_contributions WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'customers'"))
    op.execute(sa.text("UPDATE module_contributions SET label = 'Equipe e funções', group_key = 'ACESSOS' WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'team'"))
    op.execute(sa.text("UPDATE module_contributions SET label = 'Terminais e produção' WHERE surface = 'MANAGEMENT_NAV' AND contribution_key = 'devices'"))
