# Checkpoint de continuidade — Owner Financeiro SaaS

Atualizado em: **28 de agosto de 2026**

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
- recebimentos e inadimplência continuam explicitamente **Em implementação**;
- nenhuma rota ou consulta usa módulos de venda, caixa, pagamento, recebível,
  estoque ou BI do tenant.

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
```

Os três comandos exigem `control.finance.collect`, sessão AAL2 e
`Idempotency-Key`. Consulta exige `control.finance.read`; exportação exige
`control.finance.export`.

## Matriz de verdade da tela

| Elemento | Fonte real atual | Exibe valor? | Drill-down |
|---|---|---:|---|
| MRR contratado | mensalidades de assinaturas `ACTIVE` | sim | contratos filtrados |
| Assinaturas ativas/trial | `tenant_subscriptions.status` | sim | contratos filtrados |
| Contas aptas | cadastro obrigatório completo em `saas_billing_accounts` | sim | contratos/contas |
| Faturado SaaS | faturas emitidas, excluídos rascunhos e anuladas | sim | faturas abertas na F2 |
| Saldo aberto | `balance_amount` das faturas `OPEN` | sim | faturas abertas |
| Rascunhos | faturas `DRAFT` | sim | faturas filtradas |
| Anuladas | faturas `VOID` | sim | faturas filtradas |
| Recebimentos | agregado ainda inexistente | não | Em implementação |
| Inadimplência | saldo vencido ainda não derivado | não | Em implementação |
| ARR/churn/movimentos MRR | projeção ainda inexistente | não | Fase 4 |

Na Fase 2, os estados `PARTIALLY_PAID`, `PAID`, `OVERDUE` e `UNCOLLECTIBLE`
existem apenas no vocabulário do modelo. Nenhum comando atual os produz. Eles só
serão ativados com fatos de recebimento, saldo e vencimento na Fase 3.

## Evidência desta etapa

- Python `compileall`: concluído;
- frontend `npm test`: **66/66**;
- frontend `npm run build`: concluído;
- banco isolado `dashem_pos_finance_validation`: ciclo
  **052 → 051 → 052** concluído;
- testes F2 no PostgreSQL real: **3/3**;
- triggers de snapshot e itens exercitados por tentativa real de `UPDATE` após
  emissão;
- RLS confirmado no catálogo para `saas_invoices` e `saas_invoice_lines`.
- suíte backend completa: **129/129**, com API, testes SQL e testes HTTP usando o
  mesmo `DATABASE_URL`, `ENVIRONMENT=test`, `AUTH_MODE=disabled` e
  `TEST_BASE_URL`;

Observação local permanente: o banco padrão `dashem_pos` possuía objetos da
migration 050 com marcador Alembic 049. Nenhum `stamp`, drop ou correção forçada
foi executado. O banco isolado financeiro é a evidência canônica; a divergência
do banco padrão deve ser reconciliada separadamente antes de receber migrations.

## Próxima etapa: Financeiro F3 — recebimentos e cobrança

Ordem obrigatória:

1. escolher/configurar provider real; não criar adapter falso;
2. criar `SaasPayment` e `SaasPaymentAllocation` platform-owned;
3. validar webhook assinado, sanitizar payload e garantir idempotência externa;
4. conciliar `UNKNOWN` antes de qualquer retry;
5. implementar recebimento parcial/total e saldo derivado;
6. implementar estorno/crédito como fatos compensatórios imutáveis;
7. criar job idempotente que deriva vencimento do saldo e da data;
8. implementar eventos/régua de cobrança auditados;
9. somente então liberar cards de recebido, vencido e inadimplência.

Integração fiscal da própria Dashem permanece pendente até existir provider real
selecionado. `fiscal_reference` e `provider_reference` são apenas campos de
integração; ausência de valor não equivale a documento emitido externamente.

## Fase 4 — projeções

- MRR/ARR histórico e movimentos de novo/expansão/contração/churn;
- projeção reconstruível com fórmula versionada, watermark e atraso;
- drill-down integral até assinatura, fatura e recebimento;
- validação por conjuntos financeiros fechados.

## Protocolo para a próxima sessão

1. executar `git status --short` e `git log -1 --oneline`;
2. ler este checkpoint e a seção 8 da especificação funcional/técnica;
3. confirmar `alembic current` no alvo escolhido antes de editar;
4. não usar o banco padrão divergente até sua reconciliação explícita;
5. executar os três testes mínimos de regressão;
6. iniciar pela Fase 3 na ordem acima, sem criar valores ou estados simulados;
7. atualizar este checkpoint com arquivos, migrations, testes e próximo passo;
8. fazer commit e push somente após todas as evidências passarem.
