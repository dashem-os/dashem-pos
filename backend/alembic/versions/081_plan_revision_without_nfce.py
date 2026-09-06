"""ADR-031 — nova versão dos planos, sem oferecer o que não pode ser vendido.

A migração `056` semeou os planos comerciais com `fiscal_nfce` incluído, e ela
não é alterada aqui: o que ela gravou é história, e história de contrato não se
reescreve. Um plano é uma oferta datada, e a oferta de então era aquela.

O que muda é a oferta **de agora**. A NFC-e passou a `PARTIAL` quando se
reconheceu que o único emissor é o `FakeFiscalGateway`, que fabrica a chave de
acesso — então ela sai da oferta corrente por uma **nova versão** de cada plano
que a listava, com o snapshot imutável correspondente em `service_plan_revisions`.

Três coisas que esta migração deliberadamente **não** faz:

* não desliga a NFC-e de ninguém. Contratos existentes apontam para a revisão do
  plano que assinaram, e `effective_capabilities` lê o snapshot do contrato — o
  que foi contratado continua valendo;
* não impede manter esses contratos. Renovar ou mexer em quota de um contrato que
  já carrega NFC-e continua funcionando, porque o que já está contratado é
  carregado adiante por toda a cadeia de composição (`grandfathered`);
* não impede contratar o resto. Um tenant no plano antigo segue contratando todas
  as demais capabilities normalmente; só a NFC-e deixa de ser oferecível a quem
  ainda não a tem.

E o downgrade desfaz **apenas o que esta migração fez**. Ele acha a revisão que
ela criou pela marca no motivo, e só reverte o plano cuja versão corrente é
exatamente essa. Um plano que já tinha retirado a NFC-e por conta própria antes
daqui não é tocado por nenhum dos dois sentidos — reverter pela ausência da chave
teria devolvido a NFC-e a quem a havia removido de propósito.

O snapshot publicado não é apagado no caminho de volta, e não é descuido: a
tabela de revisões é append-only por gatilho, e uma oferta que foi publicada
continua tendo sido publicada. O que volta é o ponteiro do plano.

Quando o gateway real existir, a NFC-e volta à oferta por outra versão de plano —
que é como uma oferta comercial deve mudar: por versão, não por edição do passado.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "081_plan_revision_no_nfce"
down_revision: Union[str, None] = "080_refund_cashier_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A marca que identifica as linhas desta migração. É por ela que o downgrade
# reconhece o próprio trabalho, em vez de deduzir pela ausência da capability.
REASON = (
    "NFC-e retirada da oferta corrente: emissão depende de gateway fiscal real "
    "(ADR-031). Contratos existentes seguem valendo na revisão que assinaram."
)

# Publicados como constantes para que o teste exercite exatamente o SQL que roda
# na migração, dentro de uma transação que ele desfaz.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    # 1. O snapshot imutável da nova versão, ao lado do antigo.
    f"""
    WITH alvo AS (
        SELECT id, version + 1 AS nova_versao,
               (SELECT jsonb_agg(chave ORDER BY ordem)
                  FROM jsonb_array_elements_text(capability_keys::jsonb)
                       WITH ORDINALITY AS t(chave, ordem)
                 WHERE chave <> 'fiscal_nfce') AS chaves
          FROM service_plans
         WHERE capability_keys::jsonb ? 'fiscal_nfce'
    )
    INSERT INTO service_plan_revisions (
        id, plan_id, version, code, name, description, is_active,
        store_limit, user_limit, terminal_limit, storage_limit_mib,
        capability_keys, activity_keys, monthly_price, reason, created_by, created_at
    )
    SELECT gen_random_uuid(), p.id, a.nova_versao, p.code, p.name, p.description,
           p.is_active, p.store_limit, p.user_limit, p.terminal_limit,
           p.storage_limit_mib, a.chaves::json, p.activity_keys, p.monthly_price,
           '{REASON}', NULL, now()
      FROM service_plans p
      JOIN alvo a ON a.id = p.id
     WHERE NOT EXISTS (
         SELECT 1 FROM service_plan_revisions r
          WHERE r.plan_id = p.id AND r.version = a.nova_versao
     )
    """,
    # 2. A oferta corrente passa a ser a nova versão.
    """
    UPDATE service_plans p
       SET capability_keys = (
               SELECT jsonb_agg(chave ORDER BY ordem)
                 FROM jsonb_array_elements_text(p.capability_keys::jsonb)
                      WITH ORDINALITY AS t(chave, ordem)
                WHERE chave <> 'fiscal_nfce'
           )::json,
           version = p.version + 1,
           updated_at = now()
     WHERE p.capability_keys::jsonb ? 'fiscal_nfce'
    """,
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    # 1. Restaurar o plano a partir do snapshot anterior — e só onde a versão
    #    corrente é a que esta migração criou. Nada de deduzir pela ausência da
    #    chave: um plano que retirou a NFC-e sozinho não é trabalho nosso.
    f"""
    UPDATE service_plans p
       SET capability_keys = anterior.capability_keys,
           version = anterior.version,
           updated_at = now()
      FROM service_plan_revisions marca
      JOIN service_plan_revisions anterior
        ON anterior.plan_id = marca.plan_id
       AND anterior.version = marca.version - 1
     WHERE marca.plan_id = p.id
       AND marca.version = p.version
       AND marca.reason = '{REASON}'
    """,
    # Provado em `test_the_downgrade_only_reverts_what_the_migration_itself_changed`:
    # um plano que retirou a NFC-e por conta própria antes daqui atravessa os dois
    # sentidos intocado.
    # E só. O snapshot publicado **não** é apagado: `service_plan_revisions` tem
    # gatilho de imutabilidade (`service_plan_revisions_immutable`), e ele está
    # certo — uma oferta que foi publicada continua tendo sido publicada. O
    # downgrade devolve o ponteiro do plano à revisão anterior; a linha da versão
    # retirada permanece no histórico, e reaplicar o upgrade a reaproveita em vez
    # de inserir outra.
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(sa.text(statement))
