"""Management overview permission and aggregate contract.

Revision ID: 018_management_overview
Revises: 017_permission_engine
Create Date: 2026-08-23 17:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018_management_overview"
down_revision: Union[str, None] = "017_permission_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO permissions (key, name, description, capability_key, created_at)
        VALUES ('management.read', 'Consultar visão gerencial',
                'Acessa métricas agregadas persistidas do Dashem Gestão.', NULL, now())
    """))
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'management.read'
        FROM role_profiles rp
        WHERE rp.is_system = true
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'AUDITOR')
    """))


def downgrade() -> None:
    op.execute("DELETE FROM role_profile_permissions WHERE permission_key = 'management.read'")
    op.execute("DELETE FROM permissions WHERE key = 'management.read'")
