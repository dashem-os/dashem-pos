# ADR-011 — Projeções persistidas para Business Intelligence

Status: aceito no S17  
Data: 23 de agosto de 2026

## Contexto

O Dashem precisa oferecer indicadores operacionais multi-site sem transferir o
histórico transacional para o navegador, sem alterar fatos financeiros e sem
mostrar números cuja origem ou atualização não possam ser explicadas.

## Decisão

Vendas, pagamentos, estornos, recebíveis, mesas, produção, transferências,
marketplace e estoque continuam sendo as fontes de verdade. O BI é um read model
descartável composto por fatos diários e um estado de projeção por tenant e
unidade.

A projeção:

- reconstrói somente um intervalo explícito e limitado;
- substitui os fatos desse intervalo na mesma transação;
- preserva dimensões de terminal, operador e canal quando a fonte as possui;
- publica versão, watermark, competência, instante e estado da atualização;
- aplica RLS e contexto de tenant/unidade tanto no agregado quanto no drill-down;
- registra atualização em auditoria e outbox.

Fórmulas são parte do contrato versionado da API. O frontend recebe agregados e
fontes paginadas; não recebe todo o histórico para recalcular métricas.

## Consequências

- atrasos são visíveis e podem gerar alertas, em vez de parecerem dados atuais;
- o read model pode ser apagado e reconstruído sem modificar o core;
- correções de fórmula exigem nova versão e rebuild do período afetado;
- fontes sem determinada dimensão aparecem no escopo agregado, sem inferência;
- evolução para workers assíncronos não altera o contrato de leitura.
