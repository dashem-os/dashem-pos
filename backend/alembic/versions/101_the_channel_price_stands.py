"""O preço declarado pelo canal fica no pedido, e a oferta local fica ao lado.

S10.1, passo 5 — decisão D1 e requisito R11 (docs/product/proposta-s10-1-channel-hub.md, §3.5 e §8).

`external_order_lines` passa a guardar o preço unitário da oferta local
(`local_unit_amount`, catálogo da loja mais complementos mapeados) e a diferença
da linha (`difference_amount`) entre o valor líquido declarado pelo canal e a
oferta local.

`external_order_mappings` passa a guardar o subtotal da oferta local dos itens
ativos (`local_items_amount`) e a diferença total de mercadoria do pedido
(`difference_amount`) frente à oferta local.

O catálogo (`product_prices`) não é alterado. As políticas de RLS de ambas as
tabelas já estão ativas desde a migração 099.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "101_the_channel_price_stands"
down_revision: Union[str, None] = "100_the_notice_leaves"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 4)


def upgrade() -> None:
    op.add_column("external_order_mappings", sa.Column("local_items_amount", MONEY, nullable=True))
    op.add_column("external_order_mappings", sa.Column("difference_amount", MONEY, nullable=True))
    op.add_column("external_order_lines", sa.Column("local_unit_amount", MONEY, nullable=True))
    op.add_column("external_order_lines", sa.Column("difference_amount", MONEY, nullable=True))


def downgrade() -> None:
    op.drop_column("external_order_lines", "difference_amount")
    op.drop_column("external_order_lines", "local_unit_amount")
    op.drop_column("external_order_mappings", "difference_amount")
    op.drop_column("external_order_mappings", "local_items_amount")
