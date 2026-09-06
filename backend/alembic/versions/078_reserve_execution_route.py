"""S25.1 second review — absence of a charge is only evidence when one was due.

The sweep expired any reserve whose clock ran out and that carried no
`ProviderTransaction`. For a card bound to a pinpad that is real evidence: the
system was going to send it and never did. For cash or a manual PIX it proves
nothing at all — no transaction was ever going to exist, and the money may well
be in the drawer while the parcel was never confirmed.

So the parcel records the route it was created for. Only a reserve that declared
a device can be taken back by the clock; everything else waits for a person, who
already has an explicit, permissioned and audited cancellation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "078_reserve_execution_route"
down_revision: Union[str, None] = "077_refund_without_capture"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_intents",
        sa.Column("payment_device_binding_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_intent_device_binding", "payment_intents", "payment_device_bindings",
        ["payment_device_binding_id"], ["id"],
    )
    op.create_index(
        "ix_payment_intents_payment_device_binding_id", "payment_intents",
        ["payment_device_binding_id"],
        postgresql_where=sa.text("payment_device_binding_id IS NOT NULL"),
    )
    # Reserves taken before this migration never declared a route, so none of
    # them is provably unsent. Their clocks are cleared rather than guessed at.
    op.execute(sa.text(
        "UPDATE payment_intents SET reserve_expires_at = NULL "
        "WHERE reserve_expires_at IS NOT NULL"
    ))


def downgrade() -> None:
    op.drop_index("ix_payment_intents_payment_device_binding_id", table_name="payment_intents")
    op.drop_constraint("fk_payment_intent_device_binding", "payment_intents", type_="foreignkey")
    op.drop_column("payment_intents", "payment_device_binding_id")
