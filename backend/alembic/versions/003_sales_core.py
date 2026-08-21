"""Sales Core Schema (POS-2)

Revision ID: 003_sales_core
Revises: 002_catalog_inventory
Create Date: 2026-08-12 20:38:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = '003_sales_core'
down_revision: Union[str, None] = '002_catalog_inventory'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Customers
    op.create_table(
        'customers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('cpf_cnpj', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'cpf_cnpj', name='uq_tenant_customer_cpf_cnpj')
    )
    op.create_index(op.f('ix_customers_cpf_cnpj'), 'customers', ['cpf_cnpj'], unique=False)
    op.create_index(op.f('ix_customers_name'), 'customers', ['name'], unique=False)
    op.create_index(op.f('ix_customers_tenant_id'), 'customers', ['tenant_id'], unique=False)

    # Sales
    op.create_table(
        'sales',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('store_id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('seller_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('discount_type', sa.String(), nullable=True),
        sa.Column('requested_discount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('approved_discount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('gross_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('discount_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('net_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sales_created_at'), 'sales', ['created_at'], unique=False)
    op.create_index(op.f('ix_sales_customer_id'), 'sales', ['customer_id'], unique=False)
    op.create_index(op.f('ix_sales_seller_id'), 'sales', ['seller_id'], unique=False)
    op.create_index(op.f('ix_sales_status'), 'sales', ['status'], unique=False)
    op.create_index(op.f('ix_sales_store_id'), 'sales', ['store_id'], unique=False)
    op.create_index(op.f('ix_sales_tenant_id'), 'sales', ['tenant_id'], unique=False)

    # Sale Items
    op.create_table(
        'sale_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('sale_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('product_name', sa.String(), nullable=False),
        sa.Column('sku', sa.String(), nullable=False),
        sa.Column('unit_price', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('discount_amount', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('gross_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('net_total', sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['sale_id'], ['sales.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sale_items_product_id'), 'sale_items', ['product_id'], unique=False)
    op.create_index(op.f('ix_sale_items_product_name'), 'sale_items', ['product_name'], unique=False)
    op.create_index(op.f('ix_sale_items_sale_id'), 'sale_items', ['sale_id'], unique=False)
    op.create_index(op.f('ix_sale_items_sku'), 'sale_items', ['sku'], unique=False)
    op.create_index(op.f('ix_sale_items_tenant_id'), 'sale_items', ['tenant_id'], unique=False)

    # Barcode Unique Constraint on Products
    op.create_unique_constraint('uq_tenant_product_barcode', 'products', ['tenant_id', 'barcode'])

def downgrade() -> None:
    op.drop_constraint('uq_tenant_product_barcode', 'products', type_='unique')
    op.drop_table('sale_items')
    op.drop_table('sales')
    op.drop_table('customers')
