# ADR-007 — Roteamento de produção e KDS

Status: aceito no S11.

## Decisão

- produção é uma projeção do `OrderItem`, nunca uma segunda representação
  comercial;
- `ProductionRoutingRule` resolve o destino por store, produto, modifier e
  fulfillment. Regras de modifier substituem a rota do produto;
- `ProductionDispatch` torna cada envio idempotente e
  `ProductionTicketItem` fixa item, versão, operação e snapshot;
- alteração e cancelamento incrementam `production_version`; novo dispatch
  produz `UPDATE` ou `CANCEL` compensatório sem apagar tickets anteriores;
- o KDS transiciona tickets com versão otimista. Toda transição persiste ator,
  dispositivo, horário, versão, auditoria e outbox;
- pontos indisponíveis mantêm ticket no backlog. Impressora só pode ser criada
  com referência de configuração persistida;
- preço, quantidade comercial e saldo financeiro não são recalculados pela
  produção.

## Consequência

Balcão, mesa e canal externo percorrem o mesmo roteador. Falha do KDS não perde
o pedido, e duas telas não podem sobrescrever silenciosamente o trabalho uma da
outra.
