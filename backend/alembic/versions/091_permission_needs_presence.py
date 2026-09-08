"""A operação diz que precisa de presença, em vez de o código adivinhar.

O ADR-028 tornou cancelar e descontar operações de duas pessoas: quem não tem a
autoridade pede a quem tem, ali no terminal. A regra funciona — o servidor a
aplica e o PDV abre o diálogo — mas **qual** operação é assim vivia só nas
chamadas do frontend, e a Gestão não tinha como listar "o que esta pessoa faz
sozinha" sem repetir a lista num segundo lugar.

A marca passa a ser da própria permissão. Quem quiser tornar outra operação
presencial marca a linha; ninguém precisa editar duas listas para isso.

Nada muda no comportamento: a coluna nasce falsa para todas e verdadeira para
as duas que já eram presenciais.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "091_permission_needs_presence"
down_revision: Union[str, None] = "090_the_mesh_carries_the_area"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRESENCIAIS = ("sale.cancel", "sale.discount")


def upgrade() -> None:
    op.add_column(
        "permissions",
        sa.Column("requires_presence", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_permissions_requires_presence", "permissions", ["requires_presence"])
    op.execute(
        "UPDATE permissions SET requires_presence = true WHERE key IN "
        f"({', '.join(repr(chave) for chave in PRESENCIAIS)})"
    )


def downgrade() -> None:
    op.drop_index("ix_permissions_requires_presence", table_name="permissions")
    op.drop_column("permissions", "requires_presence")
