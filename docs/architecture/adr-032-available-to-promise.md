# ADR-032 — Disponibilidade prometida e compromisso de estoque

**Status:** proposto — pendente de aceite do dono do SaaS
**Data:** 2026-09-07
**Origem:** dois defeitos observados na tela em 07/09/2026, com a etapa 2 já publicada
**Relacionado:** [ADR-001](adr-001-order-versus-sale.md), [ADR-003](adr-003-table-session.md), [ADR-029](adr-029-module-boundaries-and-owner-layer.md), [ADR-033](adr-033-stock-risk-state.md), [plano corretivo](../product/inventory-operational-correction-plan.md)

## Contexto

Dois achados, ambos na tela publicada:

1. **Hambúrguer com 15 unidades e mínimo 14 aparece como "Regular".** Sobra uma
   unidade, e o sistema chama isso de saudável.
2. **Sete Coca-Colas de nove entraram na venda sem aviso**, e a falta só apareceu
   na hora do pagamento, como recusa.

O segundo não é falha da recusa: a recusa está correta e é a última barreira. É
falha de **percepção**: entre adicionar o primeiro item e pagar, o sistema sabia
o saldo e não disse nada. O caixa descobre no pior momento.

A causa comum é o modelo: hoje o estoque é **um número estático**, e a regra é
`saldo > mínimo`. Um PDV precisa de um **estado projetado** — o que já está
comprometido por vendas e comandas em aberto conta, mesmo antes de virar
movimento.

O ADR-001 continua valendo: **`OrderItem` não consome estoque**. Este ADR não o
contradiz — ele separa *comprometer* de *consumir*.

## Decisão

O estoque de uma mercadoria numa unidade passa a ter **cinco números**, não um:

| Nome no domínio | Campo/derivação | O que é |
|---|---|---|
| `on_hand` | `inventory_balances.quantity` (já existe) | o que está na prateleira |
| `reserved` | soma das reservas ativas | o que já foi prometido a uma venda ou comanda aberta |
| `available_to_promise` | `on_hand - reserved` | o que ainda pode ser prometido |
| `on_order` | soma de recebimentos pendentes | o que já foi comprado e ainda não chegou |
| `inventory_position` | `on_hand + on_order - reserved` | o que decide compra |

**A regra de qual número usar não é opcional:**

* **risco de venda** olha `available_to_promise`;
* **necessidade de compra** olha `inventory_position`.

### O compromisso é um fato próprio

Um item em venda aberta ou comanda ativa cria uma **reserva** — `soft
commitment` —, não um movimento. Modelo novo `InventoryReservation`:

| Campo | Papel |
|---|---|
| `tenant_id`, `store_id`, `product_id` | escopo, com RLS como todo o resto |
| `origin` | `SALE` ou `ORDER` |
| `sale_item_id` / `order_item_id` | quem reservou, exatamente um preenchido |
| `quantity` | quanto está prometido |
| `status` | `ACTIVE`, `RELEASED`, `CONSUMED` |
| `expires_at` | quando o carrinho abandonado devolve a mercadoria |

A reserva **nasce** ao adicionar ou aumentar o item, **muda** ao alterar a
quantidade, e **termina** de três formas: liberada (item removido, comanda ou
venda cancelada, carrinho expirado), consumida (venda concluída, quando o
movimento de saída acontece), ou expirada.

Na conclusão, dentro da mesma transação que já existe hoje:

```
reserved  -= quantidade      (reserva vira CONSUMED)
on_hand   -= quantidade      (o movimento de venda, como hoje)
```

### Duas proteções, com papéis distintos

| Camada | Onde | O que faz | O que não faz |
|---|---|---|---|
| **Percepção de risco** | ao adicionar ou alterar item | consulta o ATP, projeta o resultado, avisa e — no limite — recusa | não substitui a validação final |
| **Integridade transacional** | na conclusão do pagamento | confere o saldo com a linha bloqueada, como hoje | não é o primeiro lugar onde a pessoa descobre a falta |

A segunda continua sendo a autoridade. A primeira existe para que a segunda
quase nunca precise recusar.

### A disponibilidade é determinística

Cálculo de ATP, reserva e recusa vivem no domínio de estoque, em SQL e Python.
**Nenhuma decisão de disponibilidade depende de LLM.** A camada de inteligência
pode explicar, priorizar e sugerir; ela não decide se uma venda pode acontecer.

## Fronteiras

`InventoryReservation` referencia `sale_items` e `order_items`, que são do módulo
`operation`. Pelo ADR-029, `catalog` não importa `operation`. Portanto:

* a **tabela** e o cálculo de ATP ficam em `catalog` (`inventory_service`), sem
  importar modelos de `operation`: a reserva guarda `origin` e um id opaco;
* quem **cria e libera** reserva é `operation` (`sale_service`, `order_service`),
  chamando o serviço de estoque — a mesma direção de dependência que a baixa de
  venda já usa hoje.

O teste `test_module_boundaries.py` é o juiz.

## Consequências

* toda tela que hoje mostra "saldo" passa a poder mostrar **disponível**, e as
  duas coisas deixam de ser sinônimo;
* comandas simultâneas param de acreditar na mesma mercadoria: a ADR-003 ganha
  um efeito que ela não tinha;
* carrinho abandonado passa a precisar de expiração — sem ela, a reserva vira
  mercadoria presa;
* o histórico não muda: reserva não é movimento e não aparece em
  "Movimentações recentes".

## Alternativa recusada

**Dar baixa ao adicionar o item.** Resolveria a percepção e quebraria o
ADR-001, o histórico e a devolução: mercadoria sairia do estoque por uma venda
que ainda pode não acontecer, e cada cancelamento viraria um movimento inverso.
