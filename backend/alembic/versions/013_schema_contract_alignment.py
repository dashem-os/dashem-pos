"""Align financial and inventory schema with canonical ORM contracts.

Revision ID: 013_schema_contract_alignment
Revises: 012_tenant_rls_capability_mesh
Create Date: 2026-08-22 00:40:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013_schema_contract_alignment"
down_revision: Union[str, None] = "012_tenant_rls_capability_mesh"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NUMERIC_COLUMNS = {
    "inventory_balances": ("quantity", "minimum_stock"),
    "inventory_movements": ("quantity", "previous_balance", "new_balance"),
    "product_prices": ("cost_price", "sale_price"),
}


def upgrade() -> None:
    for table, columns in NUMERIC_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.Float(),
                type_=sa.Numeric(14, 4),
                existing_nullable=False,
                postgresql_using=f"{column}::numeric(14, 4)",
            )

    op.create_index(
        "ix_fiscal_events_created_at", "fiscal_events", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_fiscal_events_created_at", table_name="fiscal_events")
    for table, columns in NUMERIC_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.Numeric(14, 4),
                type_=sa.Float(),
                existing_nullable=False,
                postgresql_using=f"{column}::double precision",
            )
