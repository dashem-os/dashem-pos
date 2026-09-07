#!/usr/bin/env python
"""O que o defeito de sinal deixou gravado — se é que deixou.

Até esta correção, o serviço de estoque somava a quantidade recebida qualquer
que fosse o tipo do movimento. Uma perda de 5 unidades *acrescentava* 5 ao
saldo, e o movimento gravado dizia `LOSS · 5` numa linha em que o estoque subiu.
A baixa de venda, além disso, tinha commit próprio dentro de um laço por item:
falha no segundo item deixava o primeiro baixado e a venda marcada como paga.

**Existir o caminho não significa que alguém passou por ele.** Este roteiro
procura as marcas que aqueles defeitos deixariam, para que a decisão sobre dados
reais seja tomada sobre o que há, e não sobre o que poderia haver. E mede a
população que a correção passará a recusar, que é a outra metade da mesma
decisão.

Cinco procuras, cada uma com o seu significado:

* **saída com variação positiva** — movimento de `LOSS` ou `SALE` cuja variação
  aumentou o saldo. É a assinatura direta do defeito de sinal;
* **aritmética quebrada** — `saldo anterior + variação != saldo posterior` na
  própria linha. Não deveria existir em nenhuma hipótese;
* **saldo divergente do livro** — o saldo atual difere da soma das variações.
  Considera o saldo de abertura como zero, que é como o produto nasce: um
  desvio aqui é escrita que não passou pelo movimento, ou movimento perdido;
* **venda paga sem baixa completa** — venda `PAID`/`COMPLETED` com item que
  declara controle de estoque e não tem movimento de venda correspondente. É a
  marca que a falha transacional deixaria;
* **item vendido sem vínculo de baixa** — a população que **passará a ter
  devolução recusada**. A devolução ao saldo vendável agora exige baixa
  comprovada, e a prova é o vínculo entre o movimento de venda e o item. Todo
  item anterior a esse vínculo não tem como comprová-la, mesmo tendo baixado de
  fato. Esta contagem existe para dimensionar quantas devoluções passarão a
  precisar de conferência antes de serem registradas — e, sem ela, a decisão
  sobre liberar seria tomada às cegas.

**Este roteiro só lê.** Ele não corrige, não inverte linha e não compensa nada.
Movimento confirmado não é reescrito: a correção de um saldo errado é um
movimento compensatório vinculado, com justificativa e responsável, tomado
tenant a tenant pelos fluxos autenticados. Inverter linhas em massa
transformaria um histórico errado em um histórico falsificado.

**Ele lê o schema que existe, não o que vai existir.** Um levantamento que roda
*antes* da liberação encontra o banco sem as colunas que a própria mudança cria —
`inventory_balances.version` e `inventory_movements.sale_item_id` são delas. Por
isso as consultas nomeiam as colunas em vez de pedir o modelo inteiro, e a
ausência de `sale_item_id` é tratada como o que ela significa: **nenhum item tem
vínculo de baixa comprovável**, que é justamente a resposta que a decisão precisa.

**E ele não presume a origem.** Uma saída com variação positiva *pode* ser o
defeito; pode também ser importação, correção manual antiga ou dado de teste.
O roteiro entrega identificador e evidência por loja para que alguém olhe.

Uso:

    python scripts/inventory_integrity_diagnosis.py
    python scripts/inventory_integrity_diagnosis.py --csv diagnostico.csv
"""

import argparse
import csv
from decimal import Decimal

from sqlmodel import Session, select, text

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.catalog import (
    InventoryBalance, InventoryMovement, MovementTypeEnum, Product,
)
from app.models.identity import Store, Tenant
from app.models.sale import Sale, SaleItem, SaleStatusEnum


SEM_VINCULO_DE_BAIXA = "item_vendido_sem_vinculo_de_baixa"
SAIDA_POSITIVA = "saida_com_variacao_positiva"
ARITMETICA = "aritmetica_quebrada"
SALDO_DIVERGENTE = "saldo_divergente_do_livro"
VENDA_SEM_BAIXA = "venda_paga_sem_baixa"

OUTGOING = {MovementTypeEnum.LOSS, MovementTypeEnum.SALE}
VENDIDAS = {SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED}


def _tem_coluna(session: Session, tabela: str, coluna: str) -> bool:
    """A coluna existe neste banco?

    O roteiro roda contra o ambiente publicado, que está uma ou mais migrações
    atrás. Perguntar ao schema é mais honesto do que assumir que ele acompanha o
    modelo — e é o que permite dizer a verdade sobre o que se pode ou não medir.
    """
    return session.exec(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :tabela AND column_name = :coluna"
    ), params={"tabela": tabela, "coluna": coluna}).first() is not None


def _nomes(session: Session) -> tuple[dict, dict]:
    tenants = {row.id: row.name for row in session.exec(select(Tenant)).all()}
    lojas = {row.id: row.name for row in session.exec(select(Store)).all()}
    return tenants, lojas


def _achado(tipo, movimento_ou_saldo, tenants, lojas, evidencia) -> dict:
    return {
        "tipo": tipo,
        "tenant_id": str(movimento_ou_saldo.tenant_id),
        "tenant": tenants.get(movimento_ou_saldo.tenant_id, "(desconhecido)"),
        "store_id": str(movimento_ou_saldo.store_id),
        "loja": lojas.get(movimento_ou_saldo.store_id, "(desconhecida)"),
        "product_id": str(movimento_ou_saldo.product_id),
        "referencia": str(getattr(movimento_ou_saldo, "id", "")),
        "evidencia": evidencia,
    }


MOVIMENTO_COLUNAS = (
    InventoryMovement.id, InventoryMovement.tenant_id, InventoryMovement.store_id,
    InventoryMovement.product_id, InventoryMovement.movement_type,
    InventoryMovement.quantity, InventoryMovement.previous_balance,
    InventoryMovement.new_balance, InventoryMovement.reason,
    InventoryMovement.created_at,
)


def movimentos_suspeitos(session: Session, tenants, lojas) -> list[dict]:
    """As duas procuras que cabem numa linha só do livro."""
    achados = []
    for movimento in session.exec(select(*MOVIMENTO_COLUNAS)).all():
        quantidade = Decimal(str(movimento.quantity))
        anterior = Decimal(str(movimento.previous_balance))
        posterior = Decimal(str(movimento.new_balance))

        if movimento.movement_type in OUTGOING and quantidade > 0:
            achados.append(_achado(
                SAIDA_POSITIVA, movimento, tenants, lojas,
                f"{movimento.movement_type.value} com variação +{quantidade} "
                f"em {movimento.created_at:%Y-%m-%d %H:%M} · motivo: {movimento.reason or '(sem motivo)'}",
            ))
        if anterior + quantidade != posterior:
            achados.append(_achado(
                ARITMETICA, movimento, tenants, lojas,
                f"{anterior} + {quantidade} != {posterior}",
            ))
    return achados


def saldos_divergentes(session: Session, tenants, lojas) -> list[dict]:
    """O saldo atual contra a soma do que o livro registra."""
    somas: dict[tuple, Decimal] = {}
    for movimento in session.exec(select(
        InventoryMovement.tenant_id, InventoryMovement.store_id,
        InventoryMovement.product_id, InventoryMovement.quantity,
    )).all():
        chave = (movimento.tenant_id, movimento.store_id, movimento.product_id)
        somas[chave] = somas.get(chave, Decimal("0")) + Decimal(str(movimento.quantity))

    achados = []
    for saldo in session.exec(select(
        InventoryBalance.id, InventoryBalance.tenant_id, InventoryBalance.store_id,
        InventoryBalance.product_id, InventoryBalance.quantity,
    )).all():
        chave = (saldo.tenant_id, saldo.store_id, saldo.product_id)
        # Abertura zero: o produto nasce sem saldo e todo acréscimo é movimento.
        esperado = somas.get(chave, Decimal("0"))
        atual = Decimal(str(saldo.quantity))
        if atual != esperado:
            achados.append(_achado(
                SALDO_DIVERGENTE, saldo, tenants, lojas,
                f"saldo {atual}, livro {esperado}, diferença {atual - esperado}",
            ))
    return achados


def vendas_sem_baixa(session: Session, tenants, lojas) -> list[dict]:
    """A marca que a falha transacional deixaria: venda paga, estoque intacto."""
    baixados = {
        (movimento.tenant_id, movimento.store_id, movimento.product_id)
        for movimento in session.exec(select(
            InventoryMovement.tenant_id, InventoryMovement.store_id,
            InventoryMovement.product_id,
        ).where(InventoryMovement.movement_type == MovementTypeEnum.SALE)).all()
    }
    controlados = {
        produto.id for produto in session.exec(select(
            Product.id, Product.tracks_inventory,
        )).all() if produto.tracks_inventory
    }
    achados = []
    for venda in session.exec(select(
        Sale.id, Sale.tenant_id, Sale.store_id, Sale.status, Sale.occurred_at,
    ).where(Sale.status.in_(VENDIDAS))).all():
        itens = session.exec(select(
            SaleItem.id, SaleItem.product_id, SaleItem.product_name,
            SaleItem.quantity, SaleItem.tracks_inventory_snapshot,
        ).where(SaleItem.sale_id == venda.id)).all()
        for item in itens:
            if not item.tracks_inventory_snapshot and item.product_id not in controlados:
                continue
            if (venda.tenant_id, venda.store_id, item.product_id) in baixados:
                continue
            achados.append({
                "tipo": VENDA_SEM_BAIXA,
                "tenant_id": str(venda.tenant_id),
                "tenant": tenants.get(venda.tenant_id, "(desconhecido)"),
                "store_id": str(venda.store_id),
                "loja": lojas.get(venda.store_id, "(desconhecida)"),
                "product_id": str(item.product_id),
                "referencia": str(venda.id),
                "evidencia": (
                    f"venda {venda.status.value} em {venda.occurred_at:%Y-%m-%d} "
                    f"com {item.quantity} de '{item.product_name}' sem movimento de venda"
                ),
            })
    return achados


def vendas_sem_vinculo(session: Session, tenants, lojas) -> list[dict]:
    """Itens vendidos cuja baixa não pode ser comprovada pelo vínculo.

    Não é o mesmo que "venda paga sem baixa": aqui o movimento pode existir e
    ter acontecido — ele só não aponta para o item que o causou, porque o
    vínculo é posterior. A distinção importa, e a recusa da devolução diz
    exatamente isso: não é possível comprovar, não que a mercadoria ficou.

    O número que sai daqui é o tamanho do problema operacional: quantas
    devoluções passarão a exigir conferência antes de serem registradas.
    """
    # Sem a coluna, nenhum item tem vínculo — e isso não é uma limitação do
    # levantamento, é o fato que ele precisa relatar: no schema publicado de hoje
    # **toda** devolução ao saldo vendável passaria a exigir conferência.
    if _tem_coluna(session, "inventory_movements", "sale_item_id"):
        # Coluna única devolve o valor, não uma linha.
        com_vinculo = {
            vinculo
            for vinculo in session.exec(select(InventoryMovement.sale_item_id).where(
                InventoryMovement.movement_type == MovementTypeEnum.SALE,
            )).all()
            if vinculo is not None
        }
    else:
        com_vinculo = set()

    achados = []
    for venda in session.exec(select(
        Sale.id, Sale.tenant_id, Sale.store_id, Sale.status, Sale.occurred_at,
    ).where(Sale.status.in_(VENDIDAS))).all():
        itens = session.exec(select(
            SaleItem.id, SaleItem.product_id, SaleItem.product_name,
            SaleItem.quantity, SaleItem.tracks_inventory_snapshot,
        ).where(SaleItem.sale_id == venda.id)).all()
        for item in itens:
            # O critério é o mesmo que `return_sold_item` aplica: o snapshot do
            # item, e só ele. Usar também o produto de hoje contaria itens que a
            # devolução nem verifica, e o número deixaria de ser a população que
            # será recusada — que é a única coisa que este levantamento decide.
            if not item.tracks_inventory_snapshot:
                continue
            if item.id in com_vinculo:
                continue
            achados.append({
                "tipo": SEM_VINCULO_DE_BAIXA,
                "tenant_id": str(venda.tenant_id),
                "tenant": tenants.get(venda.tenant_id, "(desconhecido)"),
                "store_id": str(venda.store_id),
                "loja": lojas.get(venda.store_id, "(desconhecida)"),
                "product_id": str(item.product_id),
                "referencia": str(item.id),
                "evidencia": (
                    f"venda {venda.status.value} de {venda.occurred_at:%Y-%m-%d} "
                    f"com {item.quantity} de '{item.product_name}': devolução ao "
                    "saldo vendável exigirá conferência"
                ),
            })
    return achados


def diagnose(session: Session) -> list[dict]:
    tenants, lojas = _nomes(session)
    return (
        movimentos_suspeitos(session, tenants, lojas)
        + saldos_divergentes(session, tenants, lojas)
        + vendas_sem_baixa(session, tenants, lojas)
        + vendas_sem_vinculo(session, tenants, lojas)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", metavar="ARQUIVO",
                        help="exportar o levantamento completo, sem corte")
    args = parser.parse_args()

    with Session(engine) as session:
        set_platform_db_context(session)
        vinculo_existe = _tem_coluna(session, "inventory_movements", "sale_item_id")
        achados = diagnose(session)

    if not vinculo_existe:
        print("Este banco ainda não tem a coluna `inventory_movements.sale_item_id`.")
        print("Sem ela nenhum item de venda tem baixa comprovável, e a contagem")
        print("abaixo é a população inteira — o que a correção passará a recusar")
        print("enquanto o histórico não for tratado.")
        print()

    rotulos = {
        SAIDA_POSITIVA: "Saída com variação positiva (assinatura do defeito de sinal)",
        ARITMETICA: "Aritmética quebrada na própria linha",
        SALDO_DIVERGENTE: "Saldo divergente da soma do livro",
        VENDA_SEM_BAIXA: "Venda paga com item controlado sem baixa",
        SEM_VINCULO_DE_BAIXA: "Item vendido sem vínculo de baixa (devolução exigirá conferência)",
    }
    for tipo, rotulo in rotulos.items():
        do_tipo = [achado for achado in achados if achado["tipo"] == tipo]
        lojas_atingidas = {achado["store_id"] for achado in do_tipo}
        print(f"{rotulo}: {len(do_tipo)}"
              + (f" · {len(lojas_atingidas)} loja(s)" if do_tipo else ""))
    print()

    if args.csv:
        campos = ["tipo", "tenant_id", "tenant", "store_id", "loja",
                  "product_id", "referencia", "evidencia"]
        with open(args.csv, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=campos)
            writer.writeheader()
            writer.writerows(achados)
        print(f"Levantamento completo exportado em {args.csv} ({len(achados)} linhas).")
    elif achados:
        print("Use --csv para o levantamento completo. Amostra:")
        for achado in achados[:20]:
            print(f"  {achado['tipo']:32} {achado['loja']:24} {achado['evidencia']}")
        if len(achados) > 20:
            print(f"  ... e mais {len(achados) - 20}; a tela é amostra, o CSV é o dado.")
    else:
        print("Nenhuma marca dos defeitos encontrada neste banco.")

    print()
    print("Escopo e limites deste levantamento:")
    print("  · ele SÓ LÊ. Não inverte linha, não compensa saldo e não corrige nada;")
    print("  · achado é indício, não veredito. Saída positiva pode ser o defeito,")
    print("    e pode ser importação, correção manual antiga ou dado de teste;")
    print("  · o saldo esperado assume abertura zero. Estoque carregado por outro")
    print("    caminho que não o movimento aparece aqui como divergência legítima;")
    print("  · corrigir dado real é movimento compensatório vinculado, com")
    print("    justificativa e responsável, decidido tenant a tenant — nunca em massa;")
    print("  · item sem vínculo de baixa NÃO é item sem baixa. O movimento pode ter")
    print("    acontecido e apenas não apontar para o item, porque o vínculo é")
    print("    posterior. O número mede quantas devoluções passarão a exigir")
    print("    conferência, e não quantas vendas deixaram de baixar estoque.")
    return 0 if not achados else 2


if __name__ == "__main__":
    raise SystemExit(main())
