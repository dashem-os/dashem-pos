"""Cancelar e descontar saem do caixa e viram autorização de quem responde.

O perfil CAIXA saía com `sale.cancel` e `sale.discount` no próprio bolso: a
mesma pessoa que registra a venda podia desfazê-la ou baixar o preço sozinha,
sem ninguém saber. O perfil OPERADOR nunca teve, e é essa a hierarquia do
balcão — quem opera pede, quem responde pela unidade permite.

Isto não tira a operação de ninguém: com a autorização presencial (ADR-028), o
botão continua na tela do caixa e passa a exigir que o supervisor digite o
próprio código. A venda fica registrada com as duas pessoas.

SUPERVISOR, MANAGER, ADMIN, OWNER e TENANT_OWNER seguem podendo direto: são
justamente quem o caixa chama.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "089_the_till_asks_to_authorize"
down_revision: Union[str, None] = "088_the_mesh_carries_the_word"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALVO = ("sale.cancel", "sale.discount")


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM role_profile_permissions rpp
        USING role_profiles rp
        WHERE rp.id = rpp.role_profile_id
          AND rp.code = 'CASHIER'
          AND rpp.permission_key IN ('sale.cancel', 'sale.discount')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, p.key
        FROM role_profiles rp
        CROSS JOIN (VALUES ('sale.cancel'), ('sale.discount')) AS p(key)
        WHERE rp.code = 'CASHIER'
          AND NOT EXISTS (
            SELECT 1 FROM role_profile_permissions x
            WHERE x.role_profile_id = rp.id AND x.permission_key = p.key
          )
        """
    )
