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
| `id` | identidade própria |
| `tenant_id`, `store_id`, `product_id` | escopo, com RLS como todo o resto. `store_id` é o nome que a unidade tem nesta base |
| `source_type` | `CART` ou `TAB` — a natureza decide a expiração |
| `sale_id` / `order_id` | quem reservou. `order_id` é a comanda, o `tab` do desenho |
| `sale_item_id` / `order_item_id` | a linha exata, para alterar e liberar sem ambiguidade |
| `quantity` | quanto está prometido |
| `status` | `ACTIVE`, `CONSUMED`, `RELEASED`, `EXPIRED` |
| `reserved_at` | quando nasceu |
| `last_activity_at` | última alteração da venda ou comanda |
| `expires_at` | anulável — só o carrinho tem |

E o disponível é a subtração direta:

```
ATP = on_hand - Σ(quantity das reservas ACTIVE)
```

### Balcão e comanda não expiram do mesmo jeito

Decisão do dono do SaaS em 07/09/2026. **Não existe um TTL único.**

| Natureza | `expires_at` | Por quê |
|---|---|---|
| `CART` — balcão | `last_activity_at + 30 min`, **deslizante**: qualquer inclusão, remoção ou alteração renova | carrinho abandonado por meia hora não pode segurar mercadoria; "até o fechamento do caixa" prende estoque por horas, e "nunca" é pior |
| `TAB` — comanda/mesa | **nulo** | uma mesa fica aberta uma, duas, três horas legitimamente. Devolver estoque em silêncio embaixo de uma comanda viva é pior do que a reserva presa |

Comanda antiga demais gera **alerta operacional**, nunca liberação silenciosa.

A reserva **nasce** ao adicionar ou aumentar o item, **muda** ao alterar a
quantidade, e **termina** por transição explícita — item removido, venda ou
comanda cancelada, venda concluída — ou, só no carrinho, por expiração.

Na conclusão, dentro da mesma transação que já existe hoje:

```
reserva → CONSUMED
on_hand -= quantidade        (o movimento de venda, como hoje)
```

Liberar e consumir são atômicos com a operação que os causa: não existe estado
intermediário em que a mercadoria esteja fora da reserva e ainda não tenha
baixado.

**A recuperação de reserva expirada é determinística e idempotente**: ela
seleciona `CART` com `expires_at` vencido e status `ACTIVE`, marca `EXPIRED` e
não faz mais nada. Rodar duas vezes produz o mesmo resultado. Como o Background
Worker não está contratado, ela roda na abertura da tela de estoque, na abertura
do PDV e no fechamento de caixa — sem depender de processo continuamente
executável.

### Duas proteções, com papéis distintos

| Camada | Onde | O que faz | O que não faz |
|---|---|---|---|
| **Percepção de risco** | **antes** de efetivar a inclusão | calcula `atp_projetado = atp_atual − quantidade_pedida`, avisa conforme o resultado e recusa quando ultrapassa | não substitui a validação final |
| **Integridade transacional** | na conclusão do pagamento | confere o saldo com a linha bloqueada, como hoje | não é o primeiro lugar onde a pessoa descobre a falta |

A segunda continua sendo a autoridade — duas estações de PDV podem estar
disputando a mesma mercadoria, e só a transação resolve isso. A primeira existe
para que a segunda quase nunca precise recusar.

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
* carrinho abandonado expira em 30 minutos de inatividade; comanda não expira,
  e comanda velha vira alerta;
* o histórico não muda: reserva não é movimento e não aparece em
  "Movimentações recentes".

## Alternativa recusada

**Dar baixa ao adicionar o item.** Resolveria a percepção e quebraria o
ADR-001, o histórico e a devolução: mercadoria sairia do estoque por uma venda
que ainda pode não acontecer, e cada cancelamento viraria um movimento inverso.
