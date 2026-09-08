"""O que está prometido a uma venda aberta deixa de ser invisível.

Até aqui o estoque só se movia na conclusão, e entre adicionar o primeiro item e
pagar não existia nada segurando mercadoria. Três caixas podiam prometer as
mesmas nove garrafas, e a falta aparecia como recusa no pagamento — depois de o
cliente já ter escolhido. Em 07/09/2026 o banco publicado mostrava uma venda
aberta com 18 unidades de um produto cujo saldo era 16, e nenhum número do
sistema sabia disso.

A reserva é o compromisso, e não é movimento: nada entra, nada sai, o histórico
não a vê e o ADR-001 continua de pé — `OrderItem` não consome estoque, e agora
nem precisa, porque comprometer e consumir passaram a ser coisas diferentes.

Sem chave estrangeira para `sales` e `orders`: a tabela pertence ao módulo de
catálogo, que não conhece o de operação (ADR-029). O vínculo é o identificador.

`expires_at` é nulo na comanda de propósito: mesa aberta por horas é operação
legítima, e devolver estoque em silêncio embaixo dela é pior do que a reserva
presa. No balcão ele existe e desliza a cada alteração (ADR-032).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "087_inventory_reservation"
down_revision: Union[str, None] = "086_shop_language_in_navigation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCOPE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "inventory_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sale_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reserved_at", sa.DateTime(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_reservation_quantity_positive"),
    )
    for coluna in ("tenant_id", "store_id", "product_id", "source_type", "sale_id",
                   "sale_item_id", "order_id", "order_item_id", "status",
                   "reserved_at", "last_activity_at", "expires_at"):
        op.create_index(f"ix_inventory_reservations_{coluna}", "inventory_reservations", [coluna])

    # Uma linha de venda tem no máximo uma reserva viva. Sem isto, um clique
    # repetido criaria duas promessas para a mesma unidade.
    op.create_index(
        "uq_inventory_reservation_active_sale_item", "inventory_reservations",
        ["sale_item_id"], unique=True,
        postgresql_where=sa.text("status = 'ACTIVE' AND sale_item_id IS NOT NULL"),
    )
    op.create_index(
        "uq_inventory_reservation_active_order_item", "inventory_reservations",
        ["order_item_id"], unique=True,
        postgresql_where=sa.text("status = 'ACTIVE' AND order_item_id IS NOT NULL"),
    )
    # O disponível é lido por produto e unidade a cada inclusão: o índice é o
    # caminho quente da venda.
    op.create_index(
        "ix_inventory_reservations_active_scope", "inventory_reservations",
        ["tenant_id", "store_id", "product_id"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.execute('ALTER TABLE "inventory_reservations" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "inventory_reservations" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY dashem_tenant_isolation ON "inventory_reservations" FOR ALL '
        f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS dashem_tenant_isolation ON "inventory_reservations"')
    op.drop_table("inventory_reservations")
