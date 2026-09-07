"""Devolução vinculada à venda: origem, teto, condição e destino.

Devolver mercadoria era uma entrada de estoque como outra qualquer: `RETURN` com
uma quantidade e um motivo em texto livre. Nada ligava a devolução à venda de
onde a mercadoria saiu, nada impedia devolver dez de um item vendido duas vezes,
e nada distinguia mercadoria que volta à prateleira de mercadoria que voltou
imprópria — as duas somavam saldo vendável igualmente.

`sale_item_returns` guarda a devolução como fato ligado ao item de venda:

* **origem** — a venda e o item de onde a mercadoria saiu;
* **teto** — o vendido menos o já devolvido, apurado sob bloqueio do item de
  venda, para que duas solicitações simultâneas não somem além do vendido;
* **condição e destino** — mercadoria imprópria não volta ao saldo vendável, e
  fica registrada aguardando o tratamento que a etapa de almoxarifado definirá;
* **reenvio** — chave de idempotência com o hash do comando, como na contagem:
  repetir não duplica entrada, e reaproveitar a chave com outro conteúdo é
  recusado.

Devolução física e estorno financeiro continuam separados, cada um com o seu
vínculo e o seu histórico. São fatos independentes: o cliente pode receber o
dinheiro sem devolver o produto, e devolver o produto sem estorno.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "083_linked_sale_return"
down_revision: Union[str, None] = "082_stock_count_and_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCOPE = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    " OR nullif(current_setting('app.platform_access', true), '') = 'true'"
)


def upgrade() -> None:
    op.create_table(
        "sale_item_returns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        # A origem: sem ela não há teto a respeitar nem história a contar.
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        # RESALEABLE volta ao saldo vendável; UNFIT não volta, e diz para onde foi.
        sa.Column("condition", sa.String(length=24), nullable=False),
        sa.Column("destination", sa.String(length=24), nullable=False),
        # Nulo quando a mercadoria não retorna ao saldo vendável.
        sa.Column("movement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"]),
        sa.ForeignKeyConstraint(["sale_item_id"], ["sale_items.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["movement_id"], ["inventory_movements.id"]),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_return_idempotency"),
        sa.CheckConstraint("quantity > 0", name="ck_sale_item_return_positive"),
    )
    op.create_index("ix_sale_item_returns_tenant_id", "sale_item_returns", ["tenant_id"])
    op.create_index("ix_sale_item_returns_sale_item_id", "sale_item_returns", ["sale_item_id"])
    op.create_index("ix_sale_item_returns_product_id", "sale_item_returns", ["product_id"])
    op.execute('ALTER TABLE "sale_item_returns" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "sale_item_returns" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY dashem_tenant_isolation ON "sale_item_returns" FOR ALL '
        f"USING ({SCOPE}) WITH CHECK ({SCOPE})"
    )


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS dashem_tenant_isolation ON "sale_item_returns"')
    op.drop_index("ix_sale_item_returns_product_id", table_name="sale_item_returns")
    op.drop_index("ix_sale_item_returns_sale_item_id", table_name="sale_item_returns")
    op.drop_index("ix_sale_item_returns_tenant_id", table_name="sale_item_returns")
    op.drop_table("sale_item_returns")
