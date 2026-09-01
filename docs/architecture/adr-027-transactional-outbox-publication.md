# ADR-027 — Publicação transacional da outbox

**Status:** aceito  
**Data:** 2026-09-01

## Contexto

A outbox persistia eventos na mesma transação do domínio, porém o worker anterior apenas escrevia o evento no log e o marcava como processado. Isso não constitui entrega, não deixa um recibo consumível e produz um falso estado saudável. A futura integração omnichannel, TEF e delivery precisa de uma fronteira interna estável antes de qualquer adaptador externo.

## Decisão

- `outbox_events` continua sendo a fila transacional mutável.
- O worker adquire um evento com `FOR UPDATE SKIP LOCKED` e grava um lease com vencimento. Um processo interrompido pode ser retomado depois do vencimento.
- A publicação só termina quando o envelope canônico é anexado a `published_events` e a outbox é marcada `PUBLISHED` na mesma transação.
- `published_events` é um fluxo interno imutável. Cada `outbox_event_id` possui um único recibo e um hash SHA-256 do envelope.
- Falhas transitórias voltam para `PENDING` com backoff limitado. Envelope inválido ou limite de tentativas resulta em `FAILED`, sem recibo de publicação.
- `PUBLISHED` significa disponível no fluxo interno do DASHEM. Não significa aceito por adquirente, TEF, marketplace ou canal de delivery.

## Fronteira para integrações externas

Cada adaptador externo terá seu próprio registro de entrega, idempotência, tentativa, resposta do provedor e estado terminal. A confirmação externa nunca será inferida do log nem do estado da outbox. Isso permite que TEF POS Smart, iFood, 99Food, e-commerce e outros canais evoluam como módulos consumidores sem alterar a transação do domínio.

## Consequências

- Iniciar o worker passa a gerar evidência persistida e auditável; não apenas remover itens visíveis da fila.
- O worker precisa de processo continuamente executável. No Render isso requer um Background Worker pago; a instância web gratuita não deve fingir esse papel.
- A saúde do worker continua `UNKNOWN` até que o processo seja provisionado e publique heartbeat real.
- A fila pode permanecer `DEGRADED` durante a homologação sem representar perda: os eventos continuam persistidos e recuperáveis.
- O compute pago fica postergado até o gate de pré-piloto. Ele não bloqueia a construção do Owner, do tenant nem o gate funcional do Sprint 5.1; bloqueia o GO de qualquer piloto hospedado que dependa de execução assíncrona.
- Critérios, configuração, validação e rollback estão no [gate de investimento do Background Worker](../operations/background-worker-investment-gate.md).
