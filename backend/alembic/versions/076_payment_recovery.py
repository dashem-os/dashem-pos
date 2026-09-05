"""S25.1 — cancelling, expiring and diverging are not the same as failing.

S25 made the per-item reserve real, and by doing so made abandonment expensive:
a parcel stuck at PENDING holds one line of the bill, and nobody else can pay it.
The only release that existed was `fail_intent`, which declared a failure without
ever asking whether a card was still authorising — and which had no button
anywhere, so an operator had no way out at all.

This migration gives the four operations their own shapes.

`canceled_*` records a reserve given back because nothing was ever charged. It is
not a failure: nothing failed, somebody changed their mind.

`reserve_expires_at` is when the server may take an abandoned reserve back on its
own. It is set only for parcels that can be abandoned safely, and the expiry
still refuses to run if any provider transaction exists — absence of an answer is
never proof of absence of a charge.

`payment_settlement_divergences` is the table this sprint exists for. A provider
confirming a parcel that was already cancelled, or refunding one that was already
confirmed, is a financial fact that must never be discarded and must never be
applied silently. It is written here, append-only, and waits for a person.
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "076_payment_recovery"
down_revision: Union[str, None] = "075_payment_intent_payer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = (
    "('LATE_CONFIRMATION', 'LATE_FAILURE', 'EXTERNAL_CANCEL_AFTER_CONFIRM', "
    "'REFUND_REQUIRES_REVERSAL', 'UNEXPECTED_RESULT')"
)


def upgrade() -> None:
    op.add_column("payment_intents", sa.Column("canceled_at", sa.DateTime(), nullable=True))
    op.add_column("payment_intents", sa.Column("canceled_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("payment_intents", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("payment_intents", sa.Column("cancel_idempotency_key", sa.String(length=160), nullable=True))
    op.add_column("payment_intents", sa.Column("cancel_request_hash", sa.String(length=64), nullable=True))
    op.add_column("payment_intents", sa.Column("reserve_expires_at", sa.DateTime(), nullable=True))
    # The sweep looks for reserves whose clock ran out; it never scans the rest.
    op.create_index(
        "ix_payment_intents_reserve_expires_at", "payment_intents", ["reserve_expires_at"],
        postgresql_where=sa.text("reserve_expires_at IS NOT NULL"),
    )

    op.create_table(
        "payment_settlement_divergences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_intents.id"), nullable=False),
        sa.Column("provider_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("intent_status", sa.String(length=24), nullable=False),
        sa.Column("provider_status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        # The same provider answer arriving twice is one divergence, not two.
        sa.UniqueConstraint(
            "payment_intent_id", "kind", "provider_status",
            name="uq_settlement_divergence_fact",
        ),
        sa.CheckConstraint(f"kind IN {KINDS}", name="ck_settlement_divergence_kind"),
    )
    for column in ("tenant_id", "store_id", "payment_intent_id", "kind", "created_at"):
        op.create_index(f"ix_payment_settlement_divergences_{column}", "payment_settlement_divergences", [column])
    scope = (
        "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
        " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
    )
    op.execute('ALTER TABLE "payment_settlement_divergences" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "payment_settlement_divergences" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY dashem_tenant_isolation ON "payment_settlement_divergences" FOR ALL '
        f"USING ({scope}) WITH CHECK ({scope})"
    )

    # Giving money back is not the same authority as taking it. Until today a
    # parcel was released under `checkout.payment`, the very permission used to
    # create one.
    now = datetime.utcnow()
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("key", sa.String), sa.column("name", sa.String),
            sa.column("description", sa.Text), sa.column("capability_key", sa.String),
            sa.column("created_at", sa.DateTime),
        ),
        [{
            "key": "checkout.payment.cancel", "name": "Cancelar reserva de pagamento",
            "description": "Cancelar reserva de pagamento não enviada e devolver o saldo do item",
            "capability_key": "payments", "created_at": now,
        }],
    )
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'checkout.payment.cancel'
        FROM role_profiles rp
        WHERE rp.is_system = true
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER', 'CASHIER')
    """))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM role_profile_permissions WHERE permission_key = 'checkout.payment.cancel'"))
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'checkout.payment.cancel'"))
    op.execute('DROP POLICY IF EXISTS dashem_tenant_isolation ON "payment_settlement_divergences"')
    for column in ("created_at", "kind", "payment_intent_id", "store_id", "tenant_id"):
        op.drop_index(f"ix_payment_settlement_divergences_{column}", table_name="payment_settlement_divergences")
    op.drop_table("payment_settlement_divergences")
    op.drop_index("ix_payment_intents_reserve_expires_at", table_name="payment_intents")
    for column in (
        "reserve_expires_at", "cancel_request_hash", "cancel_idempotency_key",
        "cancel_reason", "canceled_by", "canceled_at",
    ):
        op.drop_column("payment_intents", column)
