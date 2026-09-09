"""Um contato principal por fornecedor, garantido pelo banco.

A rota desmarcava os anteriores antes de inserir o novo, e isso basta para o
caminho sequencial. **Não basta para duas requisições ao mesmo tempo**: as duas
leem "estes são os principais de hoje", as duas desmarcam, e as duas inserem. O
fornecedor termina com dois contatos principais, e a tela deixa de responder à
única pergunta que o campo existe para responder — a quem ligar.

Unicidade parcial: no máximo uma linha por fornecedor com `is_primary`. Quem
perder a corrida recebe recusa explícita, em vez de gravar o segundo principal
em silêncio.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "093_one_primary_contact_only"
down_revision: Union[str, None] = "092_who_supplies_the_goods"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Se alguma duplicidade já tiver sido gravada pela corrida, o mais antigo
    # continua sendo o principal: ele é o que a operação vinha usando.
    op.execute(
        """
        UPDATE supplier_contacts SET is_primary = false
        WHERE is_primary AND id NOT IN (
            SELECT DISTINCT ON (supplier_id) id FROM supplier_contacts
            WHERE is_primary ORDER BY supplier_id, created_at
        )
        """
    )
    op.create_index(
        "uq_supplier_primary_contact", "supplier_contacts", ["supplier_id"],
        unique=True, postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("uq_supplier_primary_contact", table_name="supplier_contacts")
