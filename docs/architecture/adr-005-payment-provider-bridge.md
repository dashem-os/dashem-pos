# ADR-005 — Provider financeiro e TEF Bridge são adapters, não regras de venda

Status: aceito no S9, em 23/08/2026.

## Decisão

O `PaymentIntent` e sua allocation continuam pertencendo ao
`CheckoutNegotiation`. `ProviderTransaction` registra somente a execução externa
de uma parcela: provider, adapter, terminal, correlation ID, NSU, autorização,
adquirente, bandeira e payload sanitizado.

O POS chama a API Dashem. A API publica um comando versionado para o Dashem TEF
Bridge; o bridge local é o único processo autorizado a conversar com SDK, DLL e
pinpad. O segredo de pareamento é exibido uma única vez e armazenado apenas como
hash. Credenciais do adquirente são referências server-side e nunca integram o
DTO de leitura.

`PROCESSING` e `UNKNOWN` não significam falha nem aprovação. Retry consulta a
transação anterior antes de criar cobrança. Somente um resultado autenticado do
bridge ou uma consulta reconciliada confirma/falha o intent. A confirmação usa o
mesmo comando idempotente do S8.

Cartão manual continua disponível somente como atestação explícita e auditada do
operador. O adapter determinístico `CONTRACT_TEST` é recusado fora de
`ENVIRONMENT=test`. SiTef, PayGo, Cappta ou outro provider só podem ser anunciados
como produtivos após credenciais, hardware e homologação externa; o contrato
interno pronto não antecipa essa certificação.
