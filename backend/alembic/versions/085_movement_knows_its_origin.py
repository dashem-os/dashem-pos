"""O movimento passa a dizer de que caminho veio, quando o caminho importa.

`ADJUSTMENT` é produzido por duas operações diferentes: a conferência da
prateleira, que compara o encontrado com o registrado, e a diferença lançada à
mão, que contorna a conferência e por isso exige `inventory.adjust.technical`.
O tipo do movimento registra o efeito e não o caminho, então o histórico lia as
duas do mesmo jeito — e apagava na tela a separação que a permissão mantém no
servidor.

O preenchimento retroativo só existe onde a origem já está **provada** por outro
fato: `inventory_counts.movement_id` aponta para o movimento que a conferência
produziu, e essas linhas recebem `COUNT`. Nenhuma linha recebe
`TECHNICAL_ADJUSTMENT` por eliminação: o ajuste técnico não deixava marca
própria antes desta migração, e deduzi-lo a partir da ausência de contagem
seria afirmar origem onde só existe desconhecimento. O histórico anterior fica
nulo, e a tela diz "Ajuste", sem inventar procedência.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "085_movement_knows_its_origin"
down_revision: Union[str, None] = "084_movement_knows_its_sale_item"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column("origin", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_inventory_movements_origin", "inventory_movements", ["origin"],
    )
    # Só o que está provado por um fato existente.
    op.execute(
        """
        UPDATE inventory_movements
        SET origin = 'COUNT'
        WHERE id IN (SELECT movement_id FROM inventory_counts WHERE movement_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_origin", table_name="inventory_movements")
    op.drop_column("inventory_movements", "origin")
