"""O menu fala a língua de quem vende, não a do modelo de dados.

"Sortimento" é o nome do agregado no domínio: um conjunto curado publicado por
unidade e contexto. Quem opera uma padaria chama aquilo de cardápio, e quem
opera uma loja chama de catálogo. O rótulo do menu passa a ser o segundo, e o
primeiro continua existindo onde ele pertence — no código, no banco e nesta
migração.

Só o rótulo muda. `contribution_key`, rota, permissão e ordenação continuam os
mesmos: nada que o frontend resolve por chave se move.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "086_shop_language_in_navigation"
down_revision: Union[str, None] = "085_movement_knows_its_origin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE module_contributions
        SET label = 'Cardápios'
        WHERE contribution_key = 'assortments' AND surface = 'MANAGEMENT_NAV'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE module_contributions
        SET label = 'Sortimentos e cardápios'
        WHERE contribution_key = 'assortments' AND surface = 'MANAGEMENT_NAV'
        """
    )
