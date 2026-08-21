"""Fiscal Request Hash (POS-4 AMBER)

Revision ID: 008_fiscal_request_hash
Revises: 007_fiscal_gateway
Create Date: 2026-08-12 21:12:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '008_fiscal_request_hash'
down_revision: Union[str, None] = '007_fiscal_gateway'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('fiscal_documents', sa.Column('request_hash', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('fiscal_documents', 'request_hash')
