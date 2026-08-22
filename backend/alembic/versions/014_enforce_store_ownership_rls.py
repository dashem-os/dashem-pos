"""Enforce tenant ownership for every store-scoped row.

Revision ID: 014_enforce_store_ownership_rls
Revises: 013_schema_contract_alignment
Create Date: 2026-08-22 01:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "014_enforce_store_ownership_rls"
down_revision: Union[str, None] = "013_schema_contract_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STORE_TABLES = (
    "agent_runs", "agent_tool_calls", "approval_requests", "audit_events",
    "cash_movements", "cash_sessions", "context_edges", "fiscal_documents",
    "fiscal_events", "inventory_balances", "inventory_movements", "memberships",
    "outbox_events", "payments", "product_prices", "registers", "sales",
    "sales_channels", "store_capability_overrides",
)


def _expression(table: str, *, require_store_owner: bool) -> str:
    platform = "current_setting('app.platform_access', true) = 'true'"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    if table == "memberships":
        own = "user_id = nullif(current_setting('app.user_id', true), '')::uuid"
        tenant = f"(({tenant}) OR ({own}))"
    site = """(
        nullif(current_setting('app.store_id', true), '') IS NULL
        OR store_id IS NULL
        OR store_id = nullif(current_setting('app.store_id', true), '')::uuid
    )"""
    if require_store_owner:
        ownership = f"""(
            store_id IS NULL
            OR EXISTS (
                SELECT 1 FROM stores owning_store
                WHERE owning_store.id = {table}.store_id
                  AND owning_store.tenant_id = {table}.tenant_id
            )
        )"""
        tenant = f"({tenant}) AND ({ownership}) AND ({site})"
    else:
        tenant = f"({tenant}) AND ({site})"
    return f"({platform}) OR ({tenant})"


def _replace_policy(table: str, expression: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS dashem_isolation ON "{table}"')
    op.execute(
        f'''CREATE POLICY dashem_isolation ON "{table}"
            FOR ALL
            USING ({expression})
            WITH CHECK ({expression})'''
    )


def upgrade() -> None:
    for table in STORE_TABLES:
        _replace_policy(table, _expression(table, require_store_owner=True))


def downgrade() -> None:
    for table in STORE_TABLES:
        _replace_policy(table, _expression(table, require_store_owner=False))
