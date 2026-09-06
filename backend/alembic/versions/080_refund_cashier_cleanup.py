"""ADR-030 — remover a concessão residual de estorno ao perfil CASHIER.

A primeira versão da migração `079` semeou `checkout.payment.refund` em OWNER,
TENANT_OWNER, ADMIN, MANAGER e CASHIER, copiando a lista de
`checkout.payment.cancel`. Copiar estava errado: o argumento que dispensa a
aprovação de uma segunda pessoa protege a revendedora que trabalha sozinha, e
ela não é um CASHIER — é a dona, e entra por OWNER ou ADMIN. O perfil CASHIER só
existe onde **há equipe**, que é justamente o caso em que dinheiro saindo da
gaveta pela mão de uma pessoa só merece ser decidido de propósito.

A `079` foi corrigida, mas um banco que já a aplicou não a executa de novo, e
ficaria com a concessão. Esta migração existe para essas bases convergirem. Ela é
idempotente: onde a concessão nunca existiu, não faz nada.

Conceder a CASHIER continua sendo uma decisão comercial em aberto, e voltar a
conceder é uma linha.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "080_refund_cashier_cleanup"
down_revision: Union[str, None] = "079_open_account_reversal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        DELETE FROM role_profile_permissions rpp
        USING role_profiles rp
        WHERE rp.id = rpp.role_profile_id
          AND rpp.permission_key = 'checkout.payment.refund'
          AND rp.is_system = true
          AND rp.code = 'CASHIER'
    """))


def downgrade() -> None:
    # Reverter é reconceder, e reconceder é a decisão que ainda não foi tomada.
    # O downgrade devolve o estado que a `079` original produzia, para que a
    # cadeia continue reversível sem que ninguém precise adivinhar.
    op.execute(sa.text("""
        INSERT INTO role_profile_permissions (id, role_profile_id, permission_key)
        SELECT gen_random_uuid(), rp.id, 'checkout.payment.refund'
        FROM role_profiles rp
        WHERE rp.is_system = true
          AND rp.code = 'CASHIER'
          AND NOT EXISTS (
              SELECT 1 FROM role_profile_permissions existing
              WHERE existing.role_profile_id = rp.id
                AND existing.permission_key = 'checkout.payment.refund'
          )
    """))
