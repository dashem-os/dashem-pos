"""Assortment carries the contracted business activity.

The sellable projection resolves Master Product -> Assortment -> Store -> Channel
-> Sales Context. Without an activity on the curated set, a food service tenant
can surface a hardware or perfumery catalogue on its own POS. The activity belongs
to the assortment and not to the product, because the same product may legitimately
be sold by operations of different niches.

NULL means "valid for every contracted activity", which is what every row created
before this revision needs in order to keep working.

Revision ID: 070_assortment_business_activity
Revises: 069_assortment_by_context
Create Date: 2026-09-03 02:10:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "070_assortment_business_activity"
down_revision: Union[str, None] = "069_assortment_by_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assortments",
        sa.Column("business_activity", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_assortments_business_activity",
        "assortments",
        ["business_activity"],
    )
    op.create_check_constraint(
        "ck_assortment_business_activity",
        "assortments",
        "business_activity IS NULL OR business_activity IN "
        "('FOOD_SERVICE', 'RETAIL', 'BEAUTY_RESELLER')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_assortment_business_activity", "assortments", type_="check")
    op.drop_index("ix_assortments_business_activity", table_name="assortments")
    op.drop_column("assortments", "business_activity")
