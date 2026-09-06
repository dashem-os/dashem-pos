"""S25.1 review — a refund that never captured here still is not a cancellation.

The first cut of S25.1 turned a provider `REFUNDED` on an open parcel into
`cancel_intent`. That reads the event as "nothing happened", and it is not what
happened: money left the customer and came back at the acquirer. The parcel
produced no payment for the shop, so the line must become payable again — but
the movement is a fact and has to stay visible.

`REFUND_WITHOUT_CAPTURE` is that fact. The parcel is closed as failed, which is
true (an attempt happened and produced nothing), and the divergence records that
a reversal took place outside.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "077_refund_without_capture"
down_revision: Union[str, None] = "076_payment_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BEFORE = (
    "('LATE_CONFIRMATION', 'LATE_FAILURE', 'EXTERNAL_CANCEL_AFTER_CONFIRM', "
    "'REFUND_REQUIRES_REVERSAL', 'UNEXPECTED_RESULT')"
)
AFTER = (
    "('LATE_CONFIRMATION', 'LATE_FAILURE', 'EXTERNAL_CANCEL_AFTER_CONFIRM', "
    "'REFUND_REQUIRES_REVERSAL', 'REFUND_WITHOUT_CAPTURE', 'STATE_REGRESSION_REFUSED', "
    "'UNEXPECTED_RESULT')"
)


def upgrade() -> None:
    op.drop_constraint("ck_settlement_divergence_kind", "payment_settlement_divergences", type_="check")
    op.create_check_constraint(
        "ck_settlement_divergence_kind", "payment_settlement_divergences", f"kind IN {AFTER}",
    )


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM payment_settlement_divergences "
        "WHERE kind IN ('REFUND_WITHOUT_CAPTURE', 'STATE_REGRESSION_REFUSED')"
    ))
    op.drop_constraint("ck_settlement_divergence_kind", "payment_settlement_divergences", type_="check")
    op.create_check_constraint(
        "ck_settlement_divergence_kind", "payment_settlement_divergences", f"kind IN {BEFORE}",
    )
