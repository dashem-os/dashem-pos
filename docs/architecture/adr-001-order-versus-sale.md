# ADR-001 — Order e Sale são agregados distintos

- Status: aceito e implementado no S6
- Data: 2026-08-23
- Decisores: Dashem Tech

## Contexto

O fluxo de balcão atual registra uma `Sale` desde o primeiro item. Isso atende ao
checkout imediato, mas não representa mesas, comandas, KDS, delivery ou vários
lançamentos antes do fechamento financeiro. Tentar acrescentar esses estados em
`Sale` misturaria produção, atendimento, pagamento e fiscal no mesmo agregado.

## Decisão

`Order` será o agregado operacional anterior ao fechamento. Ele manterá itens,
modificadores, origem, canal, fulfillment, produção e vínculos opcionais com
cliente e mesa. Pode permanecer aberto e receber comandos idempotentes.

`Sale` continuará sendo o documento comercial/financeiro: snapshots de preço e
produto, desconto aprovado, estoque, pagamentos, caixa e fiscal. Uma `Sale` pode
ser criada a partir de um `Order` ou diretamente pelo modo COUNTER.

Transição principal:

```text
Order OPEN → atendimento/produção → fechamento → Sale → pagamentos → fiscal
COUNTER ------------------------------------------→ Sale → pagamentos → fiscal
```

## Invariantes

1. `OrderItem` não movimenta estoque nem recebe pagamento por conta própria.
2. O fechamento cria ou vincula uma `Sale` de forma idempotente.
3. A `Sale` preserva seus próprios snapshots; alterações posteriores no catálogo
   ou no order não reescrevem o documento financeiro.
4. Repetir um comando de item ou fechamento com a mesma chave não duplica efeito.
5. Eventos de order e sale usam outbox transacional.

## Consequências

O modo COUNTER permanece compatível durante a introdução de `Order`. Mesas, KDS,
transferências e delivery passam a compartilhar um núcleo operacional sem
contaminar o ledger financeiro. Há custo adicional de uma transição explícita e
de consultas que correlacionam os dois agregados.

## Implementação S6

- `Order`, `OrderItem` e `OrderCommand` possuem RLS por tenant e store;
- abertura, adição, alteração e cancelamento de item usam chaves idempotentes;
- modificadores, preço, unidade e destino de produção são snapshots do lançamento;
- cada mutação gera auditoria e outbox na mesma transação;
- vínculos com customer, table, channel e sale são opcionais e explícitos;
- o fluxo COUNTER que cria `Sale` diretamente continua coberto pela regressão.
