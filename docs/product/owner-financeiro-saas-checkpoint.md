# Checkpoint de continuidade — Owner Financeiro SaaS

Atualizado em: **29 de agosto de 2026**

Este é o documento de retomada operacional do módulo. Em uma nova conta, novo
chat ou nova sessão, leia primeiro este checkpoint e depois
[`owner-financeiro-saas.md`](owner-financeiro-saas.md). O roadmap canônico
permanece em [`roadmap-commerce-os-v2.md`](roadmap-commerce-os-v2.md), seção
S18.1.

## Regra permanente: produto sem fantasia

- texto explicativo e rótulos podem estar no código;
- valores, totais, datas e estados de negócio precisam vir de fatos persistidos;
- `0` só aparece quando o domínio e a consulta real existem;
- capacidade ainda sem fatos aparece como **Em implementação** ou **Previsto**;
- todo card numérico leva aos registros que compõem o total;
- o Owner jamais consulta venda, pedido, caixa, lucro, estoque, funcionários,
  recebíveis ou BI operacional do tenant;
- nichos, capabilities, limites e as telas comerciais existentes não podem ser
  removidos ao evoluir o Financeiro.

Regressões mínimas:

- `backend/tests/test_owner_data_boundary.py`;
- `backend/tests/test_owner_finance_f2.py`;
- `frontend/tests/owner_finance_saas.test.ts`.

## Estado exato da execução

### Fases 0 e 1 — concluídas

- fronteira Owner/tenant protegida;
- navegação lateral **Financeiro SaaS**;
- overview contratual sobre `tenant_subscriptions` reais;
- `SaasBillingAccount` platform-owned, versionada e auditada;
- permissões `control.finance.*`, overrides individuais e AAL2;
- limites de usuários, dispositivos e unidades aplicados no backend do tenant,
  sem publicar contagens de consumo ao Owner;
- storage permanece apenas limite contratual enquanto não houver medidor;
- abas Plano e cobrança, Modelos de negócio, Capabilities, Limites e Conta de
  cobrança preservadas.

### Fase 2 — faturamento SaaS concluído no escopo persistido

Entregue no código desta etapa:

- `SaasInvoice` e `SaasInvoiceLine` em
  `backend/app/models/owner_finance.py`;
- migration `052_saas_invoicing` com constraints monetárias, unicidade por
  assinatura/competência/revisão, RLS `platform-only` e triggers de imutabilidade;
- geração mensal somente para assinaturas `ACTIVE` com conta de cobrança,
  contrato ativo e plano reais;
- snapshot de versão contratual, plano, descrição, valor, competência e cadastro
  de cobrança;
- fonte incompleta não gera documento de valor zero: retorna
  `INVOICE_SOURCE_INCOMPLETE`;
- transições implementadas `DRAFT → OPEN → VOID`;
- emissão e anulação com `expected_version`, AAL2, motivo obrigatório, chave de
  idempotência, hash da requisição, ator, auditoria e outbox;
- documentos e itens emitidos protegidos contra reescrita no PostgreSQL;
- listagem paginada, filtros server-side, detalhe e exportação CSV;
- overview com total emitido, saldo aberto, rascunhos, abertas e anuladas;
- cards clicáveis e tabela de fatos reais em `FinanceSaasView.tsx`;
- recebimentos e inadimplência permaneceram explícitos como **Em implementação**
  até a entrega dos fatos da Fase 3;
- nenhuma rota ou consulta usa módulos de venda, caixa, pagamento, recebível,
  estoque ou BI do tenant.

### Fase 3 — recebimentos e cobrança concluída no escopo provider-neutral

Entregue no código desta etapa:

- `SaasPayment`, `SaasPaymentAllocation`, `SaasRefund` e
  `SaasCollectionEvent` platform-owned;
- migration `054_saas_receipts_collections` com RLS forçada, constraints,
  índices, referências e proteção de fatos imutáveis no PostgreSQL;
- recebimento manual somente com AAL2, permissão, motivo, evidência externa,
  versão da fatura e chave idempotente;
- pagamento parcial e total, saldo e estado da fatura derivados no backend;
- estorno como fato compensatório imutável, sem apagar a alocação original;
- entrada de provider com HMAC, payload estrito e idempotência externa;
- endpoint do provider responde `503` sem segredo e identidade técnica e `401`
  para assinatura inválida; não existe confirmação simulada;
- `UNKNOWN` não aloca valor e exige reconciliação explícita antes de virar
  `SUCCEEDED` ou `FAILED`;
- processo idempotente deriva `OVERDUE` de vencimento e saldo, registrando
  auditoria, outbox e evento de cobrança;
- ações de cobrança são append-only, idempotentes, sanitizadas e auditadas;
- cards de recebido, estornado, saldo vencido e faturas vencidas consultam
  agregados reais e levam ao ledger ou às faturas que formam o valor;
- seleção de provider comercial, consulta automática do provider e régua de
  mensagens externas permanecem gates de configuração, não mocks.

### Fase 4 — saúde financeira concluída no escopo reconstruível

Entregue no código desta etapa:

- `SaasFinanceDailyMetric` e `SaasFinanceSubscriptionSnapshot` platform-owned;
- migration `055_saas_finance_projections` com RLS forçada, unicidade diária,
  índices e remoção em cascata somente dos detalhes derivados;
- fórmula versionada `SAAS_FINANCE_V2`, watermark, fingerprint das fontes e
  versão de reconstrução;
- MRR somente para assinatura `ACTIVE`, valor positivo e contrato vigente
  `ACTIVE`; toda exclusão fica persistida com motivo;
- ARR como `MRR × 12` e movimentos de novo, expansão, contração, churn e net new
  calculados contra o snapshot diário anterior;
- primeiro snapshot tratado como baseline: movimentos sem período anterior e
  taxas sem denominador ficam `null` e aparecem como **Sem baseline anterior**;
- agregados de faturamento, recebimento, estorno, saldo aberto, saldo vencido,
  taxa de recebimento e inadimplência derivados somente de fatos SaaS;
- reconstrução idempotente restrita pela API à data corrente em
  `America/Sao_Paulo`, sem inventar snapshots retroativos;
- drill-down até assinatura e contrato com versões, valor anterior/atual,
  movimento, inclusão ou motivo de exclusão;
- cards clicáveis, histórico materializado e metadados de fórmula, watermark e
  fingerprint em `FinanceSaasView.tsx`;
- auditoria e outbox por tenant afetado, sem dependência de venda, caixa,
  pagamento, recebível ou BI operacional do tenant.

### Fase 5 — catálogo e descontos concluídos no escopo Owner-first

- migration `056_owner_commercial_pricing` cria revisões imutáveis de plano,
  ancora o contrato à revisão e materializa bruto, desconto e líquido;
- catálogo inicial: Essencial R$ 119, Profissional R$ 229, Performance R$ 389
  e Omnichannel R$ 649, este último inativo até o Integration Hub;
- cada plano possui pacote padrão de capabilities e limites versionados;
- desconto contratual fixo ou percentual exige razão e justificativa; desconto
  integral exige encerramento ou revisão;
- oferta inicial do Essencial é representada por desconto fixo de R$ 59,10,
  resultando em R$ 59,90 sem adulterar o preço de tabela;
- fatura preserva o snapshot da revisão do plano, cria linha negativa de
  desconto e usa `NO_PAYMENT_DUE` quando o total é zero;
- overview e projeção separam MRR bruto, desconto MRR e MRR líquido.

### Rotas disponíveis

```text
GET  /api/v1/identity/platform/finance/overview
PUT  /api/v1/identity/platform/finance/billing-accounts/{tenant_id}

GET  /api/v1/control/finance/invoices
GET  /api/v1/control/finance/invoices/export
GET  /api/v1/control/finance/invoices/{invoice_id}
POST /api/v1/control/finance/invoices/generate
POST /api/v1/control/finance/invoices/{invoice_id}/issue
POST /api/v1/control/finance/invoices/{invoice_id}/void

GET  /api/v1/control/finance/payments
GET  /api/v1/control/finance/payments/{payment_id}
POST /api/v1/control/finance/payments/manual
POST /api/v1/control/finance/payments/{payment_id}/reconcile
POST /api/v1/control/finance/payments/{payment_id}/refunds
GET  /api/v1/control/finance/collections/events
POST /api/v1/control/finance/collections/events
POST /api/v1/control/finance/collections/mark-overdue
POST /api/v1/control/finance/provider/webhooks/{provider}

GET  /api/v1/control/finance/projections/latest
GET  /api/v1/control/finance/projections
GET  /api/v1/control/finance/projections/{metric_date}
POST /api/v1/control/finance/projections/rebuild
```

Os comandos humanos de emissão, baixa, reconciliação, estorno e cobrança exigem
a permissão granular correspondente e sessão AAL2. Mutações repetíveis usam
`Idempotency-Key`; consulta exige `control.finance.read` e exportação exige
`control.finance.export`. O webhook usa HMAC e identidade técnica configurada,
sem depender da sessão humana.

## Matriz de verdade da tela

| Elemento | Fonte real atual | Exibe valor? | Drill-down |
|---|---|---:|---|
| MRR bruto/desconto/líquido | termos comerciais vigentes de assinaturas `ACTIVE` | sim | contratos filtrados |
| Assinaturas ativas/trial | `tenant_subscriptions.status` | sim | contratos filtrados |
| Contas aptas | cadastro obrigatório completo em `saas_billing_accounts` | sim | contratos/contas |
| Faturado SaaS | faturas emitidas, excluídos rascunhos e anuladas | sim | faturas abertas na F2 |
| Saldo aberto | `balance_amount` das faturas abertas, parciais e vencidas | sim | faturas |
| Rascunhos | faturas `DRAFT` | sim | faturas filtradas |
| Anuladas | faturas `VOID` | sim | faturas filtradas |
| Recebido SaaS | alocações confirmadas menos estornos | sim | ledger de pagamentos |
| Estornado | fatos `SaasRefund` persistidos | sim | ledger de pagamentos |
| Saldo vencido | saldo de faturas `OVERDUE` derivadas pelo backend | sim | faturas vencidas |
| Faturas vencidas | contagem de faturas `OVERDUE` | sim | faturas vencidas |
| MRR/ARR diário | `SaasFinanceDailyMetric`, assinatura e contrato versionados | sim, após materialização | assinaturas/contratos incluídos |
| Novo/expansão/contração/churn | comparação com snapshot diário anterior | sim; `null` no primeiro baseline | assinaturas por movimento |
| Taxas de recebimento/inadimplência | faturas, alocações e estornos SaaS | sim quando há denominador | pagamentos/faturas |

Os estados `PARTIALLY_PAID`, `PAID` e `OVERDUE` agora são produzidos somente por
pagamentos, estornos, saldo e data de corte persistidos. `UNCOLLECTIBLE` continua
sem comando até existir uma política explícita; portanto não é inferido pela UI.

## Evidência desta etapa

- frontend `npm test`: **66/66**;
- frontend `npm run build`: concluído;
- banco vazio isolado `dashem_ci_recovery_053`: ciclo completo
  **base → 053 → base → 053** concluído;
- `alembic check`: **sem novas operações detectadas**;
- backup e restauração PostgreSQL 15: revisão de origem e restaurada
  **053_secure_function_paths**, com `saas_invoices` presente;
- testes focados do Financeiro, permissões e fronteira Owner/tenant: **29/29**;
- triggers de snapshot e itens exercitados por tentativa real de `UPDATE` após
  emissão;
- RLS confirmado no catálogo para `saas_invoices` e `saas_invoice_lines`.
- suíte backend completa: **130/130**, com API, testes SQL e testes HTTP usando o
  mesmo `DATABASE_URL`, `ENVIRONMENT=test`, `AUTH_MODE=disabled` e
  `TEST_BASE_URL`;

Evidência local da Fase 3 em 29 de agosto de 2026:

- frontend `npm test`: **66/66**;
- frontend `npm run build`: concluído;
- backend completo com API local e PostgreSQL: **136/136**;
- conjunto focado da Fase 3, faturamento, permissões e fronteira: **19/19**;
- banco isolado `dashem_finance_f3_validation` na revisão
  `054_saas_receipts_collections`;
- `alembic check`: **sem novas operações detectadas**;
- CI remoto da Fase 3: [Dashem Commerce OS CI #59](https://github.com/dashem-os/dashem-pos/actions/runs/33250416181),
  **Success**, com **4/4 jobs aprovados**.

Evidência local da Fase 4 em 29 de agosto de 2026:

- frontend `npm test`: **66/66**;
- frontend `npm run build`: concluído;
- backend completo com API local e PostgreSQL: **139/139**;
- conjunto focado das Fases 2, 3 e 4, permissões e fronteira: **22/22**;
- migration `055_saas_finance_projections`: downgrade para
  `054_saas_receipts_collections`, upgrade para head e `alembic check`
  concluídos;
- `alembic check`: **sem novas operações detectadas**;
- CI remoto da Fase 4: **aguardando publicação desta revisão**.

Evidência local da Fase 5 em 29 de agosto de 2026:

- frontend `npm run build`: concluído;
- migration completa `base → 056_owner_commercial_pricing` concluída em banco
  PostgreSQL isolado `dashem_pricing_migration_test2`;
- quatro planos semeados com preços, situação e snapshots de capabilities
  conferidos diretamente no banco;
- conjunto focado do Owner, faturamento e projeções: **25/25**;
- teste dedicado confirma Essencial `119,00 - 59,10 = 59,90`, snapshot da
  revisão do plano, linha de desconto e fatura zerada `NO_PAYMENT_DUE`;
- banco padrão divergente permaneceu inalterado após o upgrade transacional
  falhar na migration 050; não foi aplicado `stamp` nem reparo destrutivo.

## Recuperação do CI após a Fase 2

Os runs 53 a 56 foram publicados sem aguardar a conclusão do GitHub Actions. A
falha recorrente estava no job **Alembic canonical schema**, não nos testes de
frontend, backend ou acesso operacional.

Causas e correções registradas:

- constraints e `ON DELETE CASCADE` existentes nas migrations 049 a 052 não
  estavam representados integralmente nos models SQLAlchemy; os models agora são
  canônicos e o `alembic check` passa;
- o teste de restauração comparava a revisão restaurada com
  `048_owner_flexible_contract`, valor fixo que ficou obsoleto; agora compara a
  revisão restaurada com a revisão lida do banco de origem;
- a migration `053_secure_function_paths` fixa `search_path` em
  `pg_catalog, public` nas três funções de trigger sensíveis;
- `test_owner_finance_f2.py` impede regressão do `search_path` dessas funções.

Validação remota concluída:

- GitHub Actions
  [Dashem Commerce OS CI #57](https://github.com/dashem-os/dashem-pos/actions/runs/33217940304):
  **Success** em 1m33s;
- frontend, backend PostgreSQL/RLS, Alembic canonical schema e Operational access
  E2E: **4/4 jobs aprovados**;
- permanecem apenas avisos não bloqueantes de depreciação do runtime Node 20 nas
  versões das actions oficiais. A atualização dessas actions é manutenção de CI,
  separada da recuperação funcional e de schema aqui concluída.

Alertas externos que não são falhas do código do Financeiro:

- **Leaked Password Protection Disabled** é uma configuração do Supabase Auth e
  exige decisão/aplicação no painel;
- logs `pg_pgrst_no_exposed_schemas` pertencem à configuração/infraestrutura do
  PostgREST e devem ser diagnosticados separadamente, sem maquiar o status no
  módulo financeiro.

Observação local permanente: o banco padrão `dashem_pos` possuía objetos da
migration 050 com marcador Alembic 049. Nenhum `stamp`, drop ou correção forçada
foi executado. O banco isolado financeiro é a evidência canônica; a divergência
do banco padrão deve ser reconciliada separadamente antes de receber migrations.

## Gate externo posterior à Fase 3

O ledger e o ingresso provider-neutral estão prontos, mas nenhum provider
comercial foi escolhido. Para ativar recebimento automático em produção é
obrigatório escolher um provider real, cadastrar segredo HMAC e identidade
técnica com autoridade de plataforma, documentar consulta/retry e validar
webhooks reais. Até lá a rota permanece indisponível e a baixa manual exige
evidência; não há adapter falso.

Integração fiscal da própria Dashem permanece pendente até existir provider real
selecionado. `fiscal_reference` e `provider_reference` são apenas campos de
integração; ausência de valor não equivale a documento emitido externamente.

## Estado após a Fase 5

As Fases 0 a 5 do Financeiro SaaS estão concluídas no escopo interno
persistido. Não há nova fase funcional pendente neste recorte. Permanecem gates
externos independentes: escolher/configurar provider comercial e fiscal real,
definir transporte/política real da régua de cobrança e reconciliar o banco
padrão local divergente antes de usá-lo como alvo de migrations. Nenhum desses
gates pode ser apresentado como ativo sem a respectiva evidência externa.

## Protocolo para a próxima sessão

1. executar `git status --short` e `git log -1 --oneline`;
2. ler este checkpoint e a seção 8 da especificação funcional/técnica;
3. confirmar `alembic current` no alvo escolhido antes de editar;
4. não usar o banco padrão divergente até sua reconciliação explícita;
5. executar os três testes mínimos de regressão;
6. confirmar que o CI final da Fase 5 está verde; se não estiver, recuperar o
   run antes de iniciar qualquer novo incremento;
7. atualizar este checkpoint com arquivos, migrations, testes e próximo passo;
8. fazer commit e push somente após todas as evidências passarem;
9. após o push, acompanhar o GitHub Actions até o estado final; não iniciar a
   sprint seguinte enquanto qualquer job estiver vermelho ou ainda em execução;
10. novos incrementos dependem de decisão explícita sobre os gates externos ou
    de um novo escopo funcional, não de números ou providers simulados.
