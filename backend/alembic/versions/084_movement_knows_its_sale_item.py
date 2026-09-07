"""O movimento de venda passa a apontar para o item que o causou.

Status de venda não comprova saída de estoque. Uma venda pode estar `PAID` e não
ter baixado nada — foi o caso de toda venda fechada pela negociação antes de
07/09/2026, e é o caso de qualquer linha histórica anterior ao controle. Aceitar
devolução ao saldo vendável sobre uma dessas vendas criaria mercadoria: a entrada
aconteceria sem que nenhuma saída a tivesse precedido.

O vínculo é o que permite responder a pergunta certa — *esta mercadoria saiu?* —
em vez da pergunta aproximada, *a venda está paga?*. Ele fica nulo para as
movimentações que não vêm de venda, e nulo também para o histórico anterior a
esta migração: **ausência de vínculo não prova ausência de baixa**, e é por isso
que a devolução ao saldo vendável recusa nesse caso em vez de adivinhar. A
exceção legítima passa pelo ajuste técnico, que é explícito e restrito.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "084_movement_knows_its_sale_item"
down_revision: Union[str, None] = "083_linked_sale_return"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column("sale_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_inventory_movements_sale_item", "inventory_movements",
        "sale_items", ["sale_item_id"], ["id"],
    )
    op.create_index(
        "ix_inventory_movements_sale_item_id", "inventory_movements", ["sale_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_sale_item_id", table_name="inventory_movements")
    op.drop_constraint("fk_inventory_movements_sale_item", "inventory_movements", type_="foreignkey")
    op.drop_column("inventory_movements", "sale_item_id")
