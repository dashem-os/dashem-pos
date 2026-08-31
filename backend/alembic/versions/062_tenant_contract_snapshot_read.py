"""Allow each tenant to read only its own canonical contract snapshots.

Revision ID: 062_contract_tenant_read
Revises: 061_contract_snapshots
"""

from alembic import op


revision = "062_contract_tenant_read"
down_revision = "061_contract_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE POLICY tenant_contracts_tenant_read ON tenant_contracts FOR SELECT "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_contracts_tenant_read ON tenant_contracts")
