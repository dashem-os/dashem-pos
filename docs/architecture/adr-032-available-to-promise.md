# ADR-032 — Disponibilidade prometida e compromisso de estoque

**Status:** núcleo de balcão implementado, publicado e homologado em duas estações em 07/09/2026 (`0a7acd0`, `0d523aa`; homologação registrada em `a42e578`); extensões pendentes — ver [Situação da implementação](#situação-da-implementação)
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

## Situação da implementação

Esta seção existe porque o ADR deixou de ser só intenção no meio da própria
sprint que o citava como proposto. Ela é a resposta curta para quem for mexer
em disponibilidade: **o que já vale, e o que ainda é papel.**

### Implementado e publicado em `main`

| Contrato | Onde |
|---|---|
| A reserva é um fato próprio, com estado e origem | `InventoryReservation` (migração 087, RLS forçada, índices únicos parciais por linha ativa) |
| Reservar na inclusão, não no pagamento | `sale_service.add_sale_item` / `update_sale_item` |
| Recusa antes de o cliente escolher, com o número real | 409 — "Só há *n* disponível de '*produto*'. *m* já está em vendas abertas." |
| Cancelar e remover devolvem na hora | `release_reservations` no delete de item e no topo de `cancel_sale` |
| Concluir consome, não devolve | `consume_reservations` em `payment_service` e `negotiation_service` |
| Carrinho de balcão expira em 30 min; comanda não expira | `expire_stale_reservations`, varrido em `list_holdings` |
| Duas estações não prometem a mesma unidade | `SELECT … FOR UPDATE` sobre o saldo materializado |
| O disponível chega ao PDV | `reserved` e `available` na projeção do catálogo; `QuickProductGrid` e `ProductSearch` leem `available` (busca corrigida em `a42e578`, com fallback para `quantity`) |
| Loja que nunca carregou estoque continua vendendo | sem linha de saldo não há reserva (`0d523aa`) |

Provas: `backend/tests/test_inventory_reservation.py` (7 casos, incluindo o
cenário relatado de 16 → 10 → 7) e o portão de concorrência reescrito em
`test_pos3_gates.py`.

### Homologado no balcão, em duas estações

Em 07/09/2026 o cenário obrigatório foi percorrido com dois navegadores
simultâneos, cada um com o próprio terminal autorizado e a própria pessoa
entrando por código e PIN: operadora (CAIXA) numa estação, supervisora na
outra. Sete passos, sete como esperado
(`frontend/e2e/presentation/two_station_authorization.cjs`, capturas em
`artifacts/duas-estacoes/`):

1. a operadora promete dez das dezesseis unidades;
2. a segunda estação alcança só as seis que sobraram;
3. a sétima é recusada com o número real, antes do pagamento;
4. a operadora **não cancela sozinha** — o PDV pede autorização (P0.3);
5. PIN errado não autoriza, e a recusa aparece para quem digitou;
6. autorizada, a venda é cancelada e some da tela (P0.1);
7. liberadas as dez, a segunda estação consegue a sétima.

A travessia também expôs um defeito de escrita que só aparece na tela: a
recusa dizia "Só há 0 disponível… 16 já está em vendas abertas". Zero não é
quantidade que se anuncia e dezesseis unidades não "está" — o texto foi
reescrito e tem prova própria.

### Ainda não implementado

* **Comanda e pedido não reservam.** `order_item_id` existe na tabela e nada o
  preenche: só a venda de balcão reserva. Uma mesa aberta ainda promete
  mercadoria que o sistema não segura.
* **A escada de mensagens sobre ATP projetado antes de incluir o item.** A
  recusa por insuficiência já existe, e busca e grade já leem `available`.
  Falta o aviso progressivo baseado no saldo que restará após a inclusão,
  conforme a etapa 3.1 do plano corretivo; esse é o trabalho restante de UX-06.
* **Rota dedicada de disponibilidade e gatilhos adicionais de expiração.** A
  leitura atual usa a projeção do catálogo e a varredura roda em `list_holdings`.
  A rota em lote e os gatilhos explícitos de abertura do PDV e fechamento de
  caixa descritos no plano continuam propostos.
* **`on_order` e `inventory_position`** dependem de compras, que não existe
  como módulo (repetido aqui porque é o que falta para os cinco números).

## Alternativa recusada

**Dar baixa ao adicionar o item.** Resolveria a percepção e quebraria o
ADR-001, o histórico e a devolução: mercadoria sairia do estoque por uma venda
que ainda pode não acontecer, e cada cancelamento viraria um movimento inverso.
