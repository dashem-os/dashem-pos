"""ADR-030 — estorno de parcela dentro da conta ainda aberta.

O S25.1 fechou com este bloqueio declarado: `REFUNDED` sobre uma parcela já
confirmada não tinha para onde ir, porque o estorno que existe opera sobre
`Payment`, e `Payment` só nasce quando a venda é materializada. A mesa que
continua servindo depois que o primeiro amigo pagou a sua parte não tem
`Payment` — logo não tinha estorno.

Estorno passa a ser um fato próprio, escrito ao lado da parcela. A parcela
confirmada continua confirmada, com o valor e o autor que sempre teve, e o saldo
da conta passa a ser lido como confirmado menos revertido. Nada é reescrito.

`reverted_amount` é o coração da tabela: um estorno *pedido* não move saldo
nenhum. Só o valor comprovadamente revertido move — o movimento de caixa para
dinheiro, a resposta do provider com valor declarado para cartão, a palavra
nomeada de uma pessoa para recebimento manual.

`provider_transactions.refunded_amount` existe pela mesma razão: sem quantia,
"estornado" é uma palavra, e foi por isso que a terceira rodada do S25.1 se
recusou a liberar a reserva inteira pela palavra do provider.
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "079_open_account_reversal"
down_revision: Union[str, None] = "078_reserve_execution_route"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCOPE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
)


def _isolate(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY dashem_tenant_isolation ON "{table}" FOR ALL '
        f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
    )


def upgrade() -> None:
    op.add_column(
        "provider_transactions",
        sa.Column("refunded_amount", sa.Numeric(14, 4), nullable=True),
    )

    op.create_table(
        "payment_intent_refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column(
            "negotiation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("checkout_negotiations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "payment_intent_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        # O que o mundo devolveu, não o que alguém pediu. Zero até a prova.
        sa.Column("reverted_amount", sa.Numeric(14, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("route", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cash_movement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cash_movements.id"), nullable=True),
        sa.Column("provider_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        # Dois toques no botão são um estorno.
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_payment_intent_refund_key"),
        sa.UniqueConstraint("cash_movement_id", name="uq_payment_intent_refund_cash_movement"),
        sa.CheckConstraint("amount > 0", name="ck_payment_intent_refund_amount_positive"),
        sa.CheckConstraint("reverted_amount >= 0", name="ck_payment_intent_refund_reverted_nonnegative"),
        sa.CheckConstraint("reverted_amount <= amount", name="ck_payment_intent_refund_reverted_within_request"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'FAILED')", name="ck_payment_intent_refund_status",
        ),
        sa.CheckConstraint(
            "route IN ('CASH', 'PROVIDER', 'MANUAL')", name="ck_payment_intent_refund_route",
        ),
        # Só estorno confirmado move saldo, e confirmado sem valor revertido
        # seria exatamente a baixa improvisada que o S25.1 recusou três vezes.
        sa.CheckConstraint(
            "status <> 'CONFIRMED' OR (reverted_amount > 0 AND confirmed_at IS NOT NULL)",
            name="ck_payment_intent_refund_confirmed_has_proof",
        ),
    )
    for column in ("tenant_id", "store_id", "negotiation_id", "payment_intent_id", "status", "created_at"):
        op.create_index(f"ix_payment_intent_refunds_{column}", "payment_intent_refunds", [column])
    _isolate("payment_intent_refunds")

    op.create_table(
        "payment_intent_refund_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "negotiation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("checkout_negotiations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "payment_intent_refund_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_intent_refunds.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_items.id"), nullable=True),
        sa.Column("amount", sa.Numeric(14, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount > 0", name="ck_payment_intent_refund_allocation_amount_positive"),
    )
    for column in ("tenant_id", "negotiation_id", "payment_intent_refund_id", "order_item_id"):
        op.create_index(f"ix_payment_intent_refund_allocations_{column}", "payment_intent_refund_allocations", [column])
    _isolate("payment_intent_refund_allocations")

    # Devolver dinheiro não é a mesma autoridade que recebê-lo, e também não é a
    # de cancelar uma reserva que nunca saiu. Sem aprovação de uma segunda
    # pessoa: quem tem a permissão estorna sozinho, e responde pelo nome.
    #
    # CASHIER fica **de fora** desta semeadura, ao contrário do que acontece com
    # `checkout.payment.cancel`. O argumento que dispensa a segunda pessoa é o da
    # revendedora que trabalha sozinha — e ela não é um CASHIER, é a dona. O
    # perfil CASHIER só existe onde há equipe, que é exatamente o caso em que
    # dinheiro saindo da gaveta pela mão de uma pessoa só merece decisão
    # explícita. Conceder é uma linha; é decisão comercial em aberto.
    now = datetime.utcnow()
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("key", sa.String), sa.column("name", sa.String),
            sa.column("description", sa.Text), sa.column("capability_key", sa.String),
            sa.column("created_at", sa.DateTime),
        ),
        [{
            "key": "checkout.payment.refund", "name": "Estornar parcela de conta aberta",
            "description": "Reverter, total ou parcialmente, uma parcela de uma conta ainda aberta",
            "capability_key": "payments", "created_at": now,
        }],
    )
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'checkout.payment.refund'
        FROM role_profiles rp
        WHERE rp.is_system = true
          AND rp.code IN ('OWNER', 'TENANT_OWNER', 'ADMIN', 'MANAGER')
    """))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM role_profile_permissions WHERE permission_key = 'checkout.payment.refund'"))
    op.execute(sa.text("DELETE FROM permissions WHERE key = 'checkout.payment.refund'"))
    op.execute('DROP POLICY IF EXISTS dashem_tenant_isolation ON "payment_intent_refund_allocations"')
    for column in ("tenant_id", "negotiation_id", "payment_intent_refund_id", "order_item_id"):
        op.drop_index(f"ix_payment_intent_refund_allocations_{column}", table_name="payment_intent_refund_allocations")
    op.drop_table("payment_intent_refund_allocations")
    op.execute('DROP POLICY IF EXISTS dashem_tenant_isolation ON "payment_intent_refunds"')
    for column in ("tenant_id", "store_id", "negotiation_id", "payment_intent_id", "status", "created_at"):
        op.drop_index(f"ix_payment_intent_refunds_{column}", table_name="payment_intent_refunds")
    op.drop_table("payment_intent_refunds")
    op.drop_column("provider_transactions", "refunded_amount")
