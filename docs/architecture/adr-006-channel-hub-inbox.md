# ADR-006 — Channel Hub e inbox durável

Status: aceito no S10.

## Contexto

Pedidos de mesa, balcão e marketplace precisam convergir para o mesmo `Order`
canônico. Integrar cada marketplace diretamente à operação criaria lógica de
pedido, pagamento e produção duplicada, além de tornar a venda local dependente
da disponibilidade de terceiros.

## Decisão

- `MerchantConnection` representa uma conexão por tenant, store e merchant. Seu
  estado inicial é `NOT_CONNECTED`; apenas o adapter validado pode torná-la
  `CONNECTED`.
- o webhook é autenticado por HMAC. O segredo é exibido uma vez e somente seu
  hash é armazenado;
- `ChannelInboxEvent` persiste o payload antes do acknowledgment e registra
  processamento, duplicidade ou quarentena;
- deduplicação ocorre por evento do provider e por pedido externo;
- o adapter normaliza o payload, mas a criação percorre o mesmo `order_service`
  usado pelas demais origens;
- pagamento já recebido pelo marketplace é origem `MARKETPLACE` e não cria TEF
  nem pagamento local;
- mensagens de retorno são outbox persistida e idempotente;
- adapters de contrato existem somente no ambiente de teste. Sem credencial e
  homologação reais, iFood/99Food permanecem honestamente não conectados.

## Consequências

Falhas externas não interrompem o POS local. Eventos inválidos são observáveis e
não produzem pedido parcial. O S11 passa a ser responsável por encaminhar itens
de qualquer origem à produção, mantendo Channel Hub fora do núcleo financeiro.
