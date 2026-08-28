# Checkpoint de continuidade — Owner Financeiro SaaS

Atualizado em: **28 de agosto de 2026**

Este é o documento de retomada operacional do módulo. Em uma nova conta, novo
chat ou nova sessão de desenvolvimento, leia primeiro este checkpoint e depois
[`owner-financeiro-saas.md`](owner-financeiro-saas.md). O roadmap canônico
permanece em [`roadmap-commerce-os-v2.md`](roadmap-commerce-os-v2.md), seção
S18.1.

## Regra permanente: produto sem fantasia

O Control não pode exibir número, estado positivo ou alerta financeiro sem um
fato persistido e rastreável que o sustente.

- texto explicativo e rótulos de interface podem estar no código;
- valores de negócio, totais, datas e estados nunca podem ser fixtures,
  constantes demonstrativas, respostas simuladas ou números calculados apenas
  para preencher a tela;
- `0` só aparece quando o domínio existe, a consulta real foi executada e o
  resultado comprovado é zero;
- quando o domínio ainda não existe, a interface mostra **Em implementação** ou
  **Previsto**, sem inventar total;
- `UNKNOWN`, ausência de heartbeat ou ausência de provider nunca equivale a
  saudável, pago, conciliado ou em dia;
- todo card numérico é clicável e chega aos registros que formam seu total;
- nenhuma métrica do Owner pode consultar venda, pedido, caixa, lucro, estoque,
  funcionários ou recebíveis operacionais do tenant.

Teste de regressão mínimo: `frontend/tests/owner_finance_saas.test.ts`.

## Estado exato da execução

### Concluído antes deste checkpoint

- fronteira Owner/tenant protegida por testes;
- remoção de usuários ativos, unidades em operação, caixas e vendas do Control;
- navegação lateral **Financeiro SaaS**;
- overview contratual consultando `tenant_subscriptions` reais;
- MRR contratado como soma server-side das mensalidades de assinaturas `ACTIVE`;
- cards contratuais com drill-down;
- limites de usuários, dispositivos e unidades aplicados no backend;
- storage explicitamente marcado como contratual e sem medição;
- saúde técnica baseada em sondagens e evidências reais.

### Incremento atual — Fundação financeira honesta

Implementado no código, aguardando o commit desta entrega:

- agregado platform-owned `SaasBillingAccount` em
  `backend/app/models/owner_finance.py`;
- migration `050_saas_finance_foundation` com RLS platform-only, backfill apenas
  de cadastro/contrato e versão concorrente da assinatura;
- conta de cobrança criada/atualizada junto do contrato, sem consultar operação
  do estabelecimento;
- proteção otimista do contrato por `expected_contract_version`, retornando
  `409` quando outra sessão já salvou nova versão;
- remoção do antigo `billing_status` manual, que permitia declarar atraso ou
  adimplência sem fatura;
- overview informa disponibilidade dos fatos (`subscriptions`,
  `billing_accounts`, `invoices`, `payments`, `delinquency`);
- faturas, recebimentos e inadimplência aparecem como **Em implementação**;
- tabela contratual abre diretamente o workspace do cliente;
- conta apta significa apenas cadastro fiscal e contato completos; não significa
  que houve emissão, pagamento ou conciliação.

### Evidência executada nesta etapa

- frontend: `npm test` — **66/66**;
- frontend: `npm run build` — concluído;
- backend selecionado: **19/19** em `test_owner_console.py`,
  `test_owner_p0.py` e `test_owner_data_boundary.py`;
- Python: `compileall` concluído;
- migration 050 aplicada ao PostgreSQL local.
- banco isolado `dashem_pos_finance_validation`: migrations **001 → 050**
  executadas do zero e ciclo **050 → 049 → 050** concluído;
- suíte backend completa: **106/119 passaram**. As 13 falhas são dos testes HTTP
  S6–S17 apontando para o backend Docker já iniciado com outro banco, enquanto
  as verificações SQL diretas usavam o banco isolado; `CONTRACT_TEST` também foi
  recusado porque esse backend não estava em `ENVIRONMENT=test`. Não são falhas
  do Financeiro, mas também não são registradas como suíte verde.

O escopo diretamente alterado permanece verde em banco isolado. Para obter uma
suíte integral comparável, a próxima sessão deve iniciar backend e testes HTTP
com o mesmo `DATABASE_URL`, `ENVIRONMENT=test` e `TEST_BASE_URL`.

## Matriz de verdade da tela

| Elemento | Fonte real atual | Pode exibir valor? | Drill-down |
|---|---|---:|---|
| MRR contratado | `tenant_subscriptions.monthly_amount`, somente `ACTIVE` | sim | assinaturas filtradas |
| Assinaturas ativas | `tenant_subscriptions.status` | sim | assinaturas filtradas |
| Em avaliação | `tenant_subscriptions.status = TRIAL` | sim | assinaturas filtradas |
| Contas aptas | `saas_billing_accounts` com cadastro obrigatório completo | sim | contratos/contas |
| Faturas | domínio ainda inexistente | não | Em implementação |
| Recebimentos | domínio ainda inexistente | não | Em implementação |
| Inadimplência | domínio ainda inexistente | não | Em implementação |
| ARR/churn/movimentos de MRR | projeção ainda inexistente | não | fase futura |

## Próximas etapas obrigatórias

### Financeiro F1.2 — concluir a fundação

1. criar permissões granulares `control.finance.*` além do papel amplo atual;
2. definir autorização de leitura, gestão de cobrança, conciliação, estorno e
   exportação;
3. preservar AAL2 para comandos e auditoria/outbox na mesma transação;
4. disponibilizar edição dedicada da conta de cobrança com controle de versão;
5. encerrar a Fase 1 somente com testes de concorrência, RLS e fronteira.

### Financeiro F2 — faturamento SaaS

1. criar `SaasInvoice` e `SaasInvoiceLine` platform-owned;
2. snapshot de contrato, plano, descrição, valor e competência;
3. gerar uma única fatura por assinatura/competência/idempotência;
4. implementar estados e transições sem reescrever documento emitido;
5. listar, detalhar e exportar faturas reais;
6. somente então liberar cards de valor faturado, saldo e vencimento.

### Financeiro F3 — recebimentos e cobrança

1. provider adapter, webhook assinado e payload sanitizado;
2. pagamentos, alocações, estornos e créditos imutáveis/compensatórios;
3. conciliação de resultado `UNKNOWN` antes de qualquer retry;
4. régua e eventos de cobrança auditados;
5. derivar inadimplência de saldo de fatura vencida;
6. somente então liberar cards de recebido e em atraso.

### Financeiro F4 — projeções

1. MRR/ARR histórico e movimentos de novo/expansão/contração/churn;
2. projeção reconstruível com versão de fórmula, watermark e atraso;
3. drill-down integral até assinatura, fatura e recebimento;
4. validação por conjuntos financeiros fechados.

## Definição de pronto do módulo

O Financeiro SaaS só está pronto quando a Dashem consegue percorrer, sem dados
do estabelecimento:

```text
Contrato versionado
  → Conta de cobrança
    → Fatura SaaS com snapshot
      → Pagamento/alocação/estorno
        → Indicador reconstruível e rastreável
```

Até lá, a nomenclatura correta da tela atual é **Saúde financeira contratual**.

## Protocolo para a próxima sessão

1. verificar `git status --short` e o último commit;
2. ler este arquivo e a seção 8 de `owner-financeiro-saas.md`;
3. confirmar a migration head e executar testes antes de editar;
4. não remover nichos, capabilities, limites nem telas existentes ao evoluir o
   Financeiro;
5. implementar somente a próxima etapa indicada acima;
6. atualizar este checkpoint com estado, arquivos, testes e próximo passo;
7. fazer commit e push somente depois das evidências locais proporcionais ao
   risco.
