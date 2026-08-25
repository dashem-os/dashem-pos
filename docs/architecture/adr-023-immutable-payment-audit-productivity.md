# ADR-023 — Gate D: auditoria imutável e produtividade reconstruível

Status: aceito no Gate D, em 25/08/2026.

## Decisão

Toda execução de pagamento físico produz uma cadeia append-only em
`payment_execution_events`. Os fatos são escritos pelo backend, na mesma unidade
de trabalho da transação do provider, e preservam o escopo completo que foi
validado antes da execução:

- tenant e unidade;
- caixa e `OperationalDevice`;
- `OperationalSession` e operador, quando a origem é um turno PIN;
- ator do evento, que pode ser uma pessoa ou o TEF Bridge;
- parcela, `PaymentDeviceBinding`, transação, valor, hash da solicitação e
  sequência.

A cadeia possui quatro estágios publicados:

1. `REQUESTED`: o pagamento foi solicitado;
2. `APPROVED`: a autoridade gerencial ou operacional e o vínculo físico foram
   validados;
3. `EXECUTED`: o comando chegou ao adapter homologado;
4. `RESULT_RECORDED`: um resultado do provider foi persistido.

Retries não criam uma segunda execução e o mesmo resultado não é registrado
duas vezes. Callbacks do TEF Bridge conservam o operador e o turno de origem,
mas registram o bridge como ator do novo evento. Assim, autoria humana e autoria
de serviço não são misturadas.

## Imutabilidade

O PostgreSQL rejeita `UPDATE` e `DELETE`, por trigger, em:

- `audit_events`;
- `provider_transaction_events`;
- `payment_execution_events`.

A aplicação somente insere novos fatos. Correções de negócio são novos eventos,
nunca reescrita do histórico. A regra está na migration, portanto continua
válida fora do ORM e também para acesso SQL direto.

## Projeção explícita de produtividade

`operational_productivity_projections` é um read model mutável e reconstruível,
agrupado por sessão operacional. Ele contém unidade, caixa, dispositivo,
operador, quantidade e valor dos estágios observados. Somente eventos ligados a
uma sessão PIN entram na produtividade do operador; uma ação gerencial sem turno
operacional continua auditada, mas não é atribuída artificialmente a um turno.

As fórmulas publicadas pela API e pela Gestão são:

- taxa de autorização = autorizados / solicitados;
- taxa de execução = executados / autorizados;
- taxa de confirmação = confirmados / executados;
- valor confirmado = soma dos resultados `CONFIRMED`.

A projeção pode ser apagada e recomposta integralmente a partir dos eventos
imutáveis. O endpoint informa watermark da fonte, versão e fórmulas; a UI não
reduz transações no navegador.

## Critérios de aceite fixos

1. solicitação, autorização, execução e resultado são fatos distintos e
   ordenados;
2. tenant, unidade, caixa, dispositivo, sessão e vínculo divergentes são
   recusados antes do primeiro evento;
3. callback de serviço não assume a identidade da pessoa;
4. retries não duplicam execução nem resultado idêntico;
5. `UPDATE` e `DELETE` das trilhas imutáveis falham no banco;
6. uma unidade não enxerga eventos ou projeções de outra unidade;
7. a produtividade é persistida, possui fórmulas publicadas e pode ser
   reconstruída dos fatos;
8. migration, rollback, testes PostgreSQL/RLS, integração TEF e build frontend
   permanecem verdes.

## Consequências

- o Gate D não depende de log textual nem de estado montado no browser;
- a trilha de autorização sobrevive a expiração ou revogação posterior do JWT;
- relatórios futuros podem adicionar novas projeções sem alterar fatos antigos;
- retenção, arquivamento e assinatura criptográfica podem evoluir sobre uma
  fronteira já append-only, sem mudar o contrato do pagamento.
