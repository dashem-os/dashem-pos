"""Catalog and Inventory Schema (POS-1)

Revision ID: 002_catalog_inventory
Revises: 001_initial_pos0
Create Date: 2026-08-12 20:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = '002_catalog_inventory'
down_revision: Union[str, None] = '001_initial_pos0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Categories
    op.create_table(
        'categories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'slug', name='uq_tenant_category_slug')
    )
    op.create_index(op.f('ix_categories_name'), 'categories', ['name'], unique=False)
    op.create_index(op.f('ix_categories_slug'), 'categories', ['slug'], unique=False)
    op.create_index(op.f('ix_categories_tenant_id'), 'categories', ['tenant_id'], unique=False)

    # Products
    op.create_table(
        'products',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('category_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('sku', sa.String(), nullable=False),
        sa.Column('barcode', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('item_type', sa.String(), nullable=False),
        sa.Column('tracks_inventory', sa.Boolean(), nullable=False),
        sa.Column('requires_fulfillment', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'sku', name='uq_tenant_product_sku')
    )
    op.create_index(op.f('ix_products_barcode'), 'products', ['barcode'], unique=False)
    op.create_index(op.f('ix_products_category_id'), 'products', ['category_id'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)
    op.create_index(op.f('ix_products_sku'), 'products', ['sku'], unique=False)
    op.create_index(op.f('ix_products_tenant_id'), 'products', ['tenant_id'], unique=False)

    # Product Prices
    op.create_table(
        'product_prices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=True),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('cost_price', sa.Float(), nullable=False),
        sa.Column('sale_price', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_product_prices_product_id'), 'product_prices', ['product_id'], unique=False)
    op.create_index(op.f('ix_product_prices_store_id'), 'product_prices', ['store_id'], unique=False)
    op.create_index(op.f('ix_product_prices_tenant_id'), 'product_prices', ['tenant_id'], unique=False)

    # Inventory Movements (SOURCE OF TRUTH)
    op.create_table(
        'inventory_movements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=False),
        sa.Column('movement_type', sa.String(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('previous_balance', sa.Float(), nullable=False),
        sa.Column('new_balance', sa.Float(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('correlation_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inventory_movements_actor_id'), 'inventory_movements', ['actor_id'], unique=False)
    op.create_index(op.f('ix_inventory_movements_correlation_id'), 'inventory_movements', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_inventory_movements_created_at'), 'inventory_movements', ['created_at'], unique=False)
    op.create_index(op.f('ix_inventory_movements_movement_type'), 'inventory_movements', ['movement_type'], unique=False)
    op.create_index(op.f('ix_inventory_movements_product_id'), 'inventory_movements', ['product_id'], unique=False)
    op.create_index(op.f('ix_inventory_movements_store_id'), 'inventory_movements', ['store_id'], unique=False)
    op.create_index(op.f('ix_inventory_movements_tenant_id'), 'inventory_movements', ['tenant_id'], unique=False)

    # Inventory Balances (PROJECTION)
    op.create_table(
        'inventory_balances',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('minimum_stock', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'store_id', 'product_id', name='uq_tenant_store_product_balance')
    )
    op.create_index(op.f('ix_inventory_balances_product_id'), 'inventory_balances', ['product_id'], unique=False)
    op.create_index(op.f('ix_inventory_balances_store_id'), 'inventory_balances', ['store_id'], unique=False)
    op.create_index(op.f('ix_inventory_balances_tenant_id'), 'inventory_balances', ['tenant_id'], unique=False)

def downgrade() -> None:
    op.drop_table('inventory_balances')
    op.drop_table('inventory_movements')
    op.drop_table('product_prices')
    op.drop_table('products')
    op.drop_table('categories')
