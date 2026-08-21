"""SaleItem Operational Snapshot Columns (POS-2)

Revision ID: 004_sale_item_op_snapshot
Revises: 003_sales_core
Create Date: 2026-08-12 20:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '004_sale_item_op_snapshot'
down_revision: Union[str, None] = '003_sales_core'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('sale_items', sa.Column('item_type_snapshot', sa.String(), nullable=False, server_default='PRODUCT'))
    op.add_column('sale_items', sa.Column('tracks_inventory_snapshot', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('sale_items', sa.Column('requires_fulfillment_snapshot', sa.Boolean(), nullable=False, server_default='false'))

def downgrade() -> None:
    op.drop_column('sale_items', 'requires_fulfillment_snapshot')
    op.drop_column('sale_items', 'tracks_inventory_snapshot')
    op.drop_column('sale_items', 'item_type_snapshot')
