"""Recoverable professional counter operation context.

Revision ID: 020_counter_operation
Revises: 019_catalog_read_model
Create Date: 2026-08-23 19:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "020_counter_operation"
down_revision: Union[str, None] = "019_catalog_read_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sales", sa.Column("register_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("sales", sa.Column("operation_mode", sa.String(), server_default="COUNTER", nullable=False))
    op.add_column("sales", sa.Column("operator_action_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sales", sa.Column("last_activity_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("fk_sales_register", "sales", "registers", ["register_id"], ["id"])
    op.create_index("ix_sales_register_id", "sales", ["register_id"])
    op.create_index("ix_sales_operation_mode", "sales", ["operation_mode"])
    op.create_index("ix_sales_last_activity_at", "sales", ["last_activity_at"])
    op.create_index(
        "uq_active_sale_terminal_operator", "sales",
        ["tenant_id", "store_id", "register_id", "seller_id"], unique=True,
        postgresql_where=sa.text(
            "register_id IS NOT NULL AND seller_id IS NOT NULL "
            "AND status IN ('DRAFT', 'CHECKOUT', 'AWAITING_PAYMENT')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_active_sale_terminal_operator", table_name="sales")
    op.drop_index("ix_sales_last_activity_at", table_name="sales")
    op.drop_index("ix_sales_operation_mode", table_name="sales")
    op.drop_index("ix_sales_register_id", table_name="sales")
    op.drop_constraint("fk_sales_register", "sales", type_="foreignkey")
    op.drop_column("sales", "last_activity_at")
    op.drop_column("sales", "operator_action_count")
    op.drop_column("sales", "operation_mode")
    op.drop_column("sales", "register_id")
