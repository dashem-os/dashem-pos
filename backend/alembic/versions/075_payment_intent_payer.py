"""S25 contract 4 — a parcel learns who paid it, not only who typed it.

`payment_intents` already knew `created_by` and `confirmed_by`. Both are the
operator: the person behind the counter who executed the payment. Nothing said
whose money it was, so a screen could not put "PAGO · Marcelo" next to a
hamburger, and a bill split between four friends looked like four parcels by the
same cashier.

Two columns, and the pair is deliberate. `payer_label` is free text, because
dividing a bill between friends must never require registering anybody.
`payer_customer_id` is optional and points at a real customer, for the day the
value is charged to Carlos's account or paid by a company. One, the other, both
or neither: the parcel stays valid, and what is not said is simply not known.

No backfill invents a payer for parcels taken before today. A parcel whose payer
was never recorded reads as unknown, which is the truth.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "075_payment_intent_payer"
down_revision: Union[str, None] = "074_product_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_intents", sa.Column("payer_label", sa.String(length=160), nullable=True))
    op.add_column(
        "payment_intents",
        sa.Column("payer_customer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_intent_payer_customer", "payment_intents", "customers",
        ["payer_customer_id"], ["id"],
    )
    # Reading a bill asks "who paid what"; the index answers it without a scan.
    op.create_index(
        "ix_payment_intents_payer_customer_id", "payment_intents", ["payer_customer_id"],
        postgresql_where=sa.text("payer_customer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_payment_intents_payer_customer_id", table_name="payment_intents")
    op.drop_constraint("fk_payment_intent_payer_customer", "payment_intents", type_="foreignkey")
    op.drop_column("payment_intents", "payer_customer_id")
    op.drop_column("payment_intents", "payer_label")
