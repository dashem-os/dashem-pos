# Owner Financeiro SaaS — especificação funcional e técnica

Status: **especificação canônica; Fases 0, 1 e 2 concluídas no escopo persistido**

Data: 28 de agosto de 2026

Superfície: **Dashem Control** (`/owner`)

Ator principal: **Platform Owner / Financeiro interno da Dashem**

Checkpoint executável para retomada em outra sessão:
[`owner-financeiro-saas-checkpoint.md`](owner-financeiro-saas-checkpoint.md).

### Política de integridade da interface

O Financeiro SaaS não usa fixtures, números demonstrativos ou estados positivos
sem evidência. Um valor zero só pode ser exibido quando o fato financeiro já
existe e sua consulta real retorna zero. Capacidade ainda não implementada deve
aparecer como **Previsto** ou **Em implementação**, sem total fictício. Textos e
rótulos podem ser estáticos; dados de negócio e estados precisam ser
persistidos, server-authoritative e rastreáveis.

## 1. Objetivo

O Owner Financeiro administra exclusivamente a saúde financeira do SaaS
Dashem: contratos recorrentes, assinaturas, faturas emitidas pela Dashem,
cobranças, recebimentos, inadimplência e indicadores de receita recorrente.

O módulo não é uma central de observação da operação dos clientes. O fato de a
Dashem fornecer o software não transfere à equipe da plataforma a
responsabilidade por acompanhar faturamento, lucro, vendas, caixas, estoque,
unidades em operação ou funcionários de cada tenant.

O trabalho do Owner termina na relação comercial entre:

```text
Dashem (fornecedora do SaaS) → contrato/assinatura/fatura → tenant (cliente)
```

O trabalho operacional e financeiro do estabelecimento permanece em:

```text
tenant → Dashem Gestão → vendas, caixa, faturamento, lucro, equipe e operação
```

## 2. Decisão de fronteira

### 2.1 Dados permitidos no Dashem Control

O Control pode conhecer apenas os dados necessários para vender, provisionar,
cobrar e sustentar o SaaS:

- identidade cadastral e fiscal da organização contratante;
- responsável contratual e contato de cobrança;
- plano, preço contratado, descontos e vigência;
- capabilities e limites previstos no contrato;
- versão do contrato e histórico de alterações comerciais;
- estado da assinatura, ciclo de cobrança e próxima competência;
- faturas emitidas pela Dashem para o tenant;
- tentativas e confirmações de pagamento dessas faturas;
- recebimentos, estornos, créditos e conciliação da receita da Dashem;
- atrasos, ações de cobrança e acordos referentes à assinatura SaaS;
- impostos e documentos fiscais emitidos pela própria Dashem;
- MRR, ARR, churn, inadimplência e demais projeções derivadas exclusivamente dos
  fatos financeiros do SaaS;
- onboarding, suporte, auditoria e saúde técnica dos componentes da plataforma.

Capabilities e limites são dados contratuais. O Control pode mostrar o que foi
contratado, mas não precisa observar o consumo operacional realizado dentro do
tenant para compor sua visão financeira.

### 2.2 Dados proibidos no Dashem Control

O Owner Financeiro, a visão geral e a Saúde da Plataforma não podem consultar,
agregar, projetar, exportar ou exibir:

- vendas, pedidos, comandas, ticket médio ou faturamento do tenant;
- lucro, margem, custo, despesas ou fluxo de caixa do tenant;
- abertura, fechamento, saldo ou quantidade de caixas abertos;
- pagamentos recebidos pelo tenant e conciliações de suas vendas;
- produtos, estoque, ruptura, fornecedores ou movimentações de inventário;
- quantidade de funcionários, operadores, gerentes ou usuários ativos;
- escalas, jornadas, produtividade ou atividade individual de colaboradores;
- quantidade de unidades efetivamente em operação;
- clientes finais, crediário, contas a receber ou inadimplência do tenant;
- documentos fiscais emitidos pelo tenant;
- qualquer série histórica ou indicador de BI do negócio do tenant.

Esses dados pertencem ao **Dashem Gestão**, sob autoridade do administrador do
tenant. A restrição vale mesmo quando o dado já existe no mesmo banco e mesmo
quando o Platform Owner possui acesso técnico privilegiado.

### 2.3 Observabilidade técnica não é observação comercial

A Saúde da Plataforma pode verificar API, banco, autenticação, filas, workers,
e-mail e integrações técnicas. Pode apresentar disponibilidade, latência,
heartbeat, backlog técnico, falhas sanitizadas e incidentes.

Ela não pode usar dados operacionais do tenant como sinal de saúde. Por exemplo,
"caixas abertos", "vendas hoje" e "usuários ativos" não são sondagens da
plataforma. Um tenant sem vendas ou sem caixa aberto pode estar perfeitamente
saudável, e essa informação não é necessária ao Owner.

## 3. Escopo funcional

### 3.1 Navegação

O Dashem Control recebe a entrada **Financeiro SaaS**, separada de **Planos
comerciais** e de **Saúde da plataforma**.

```text
Dashem Control
├── Visão geral
├── Organizações
├── Planos comerciais
├── Financeiro SaaS
│   ├── Visão financeira
│   ├── Faturas
│   ├── Recebimentos
│   ├── Inadimplência
│   └── Configuração de cobrança
├── Operações do Control
└── Saúde da plataforma
```

O termo "Financeiro" sem o qualificador "SaaS" deve ser evitado no Control para
não confundir esta superfície com o financeiro do estabelecimento.

### 3.2 Visão financeira

Estado implementado em 29 de agosto de 2026: a entrada lateral **Financeiro
SaaS** consulta assinaturas, contas de cobrança, faturas, pagamentos, alocações,
estornos e vencimentos reais. A tela apresenta valores contratuais, faturados,
recebidos, estornados e vencidos derivados no backend e com drill-down. ARR,
churn e movimentos históricos de MRR continuam previstos para a Fase 4 e não
recebem zero fictício.

A página inicial apresenta, para um período explícito:

- MRR atual;
- ARR projetado;
- MRR novo, expansão, contração e churn no período;
- clientes com assinatura paga, trial, pausada e cancelada;
- valor faturado pela Dashem;
- valor recebido pela Dashem;
- saldo em aberto e saldo vencido;
- taxa de recebimento e taxa de inadimplência;
- quantidade de faturas abertas, vencidas e pagas;
- próximos vencimentos e cobranças que exigem atenção.

Todo card deve permitir rastrear a lista de faturas, assinaturas ou recebimentos
que formam o total. Nenhum gráfico é calculado a partir de vendas ou pagamentos
realizados pelo tenant.

### 3.3 Assinatura e conta de cobrança

Cada organização possui uma conta de cobrança vinculada ao contrato vigente.
Ela permite:

- consultar responsável e endereço de cobrança;
- consultar plano, capabilities e valor mensal contratado;
- definir dia de vencimento e forma de pagamento da assinatura;
- acompanhar trial, ativação, pausa, cancelamento e encerramento;
- consultar próxima competência e próxima data de vencimento;
- aplicar desconto comercial com motivo e vigência;
- alterar contrato com nova versão auditada;
- consultar a linha do tempo comercial e financeira do SaaS.

Alterar o contrato não reescreve faturas já emitidas. Uma mudança futura deve
afetar a competência seguinte ou gerar ajuste explícito, conforme a data de
efeito registrada.

### 3.4 Faturas da Dashem

O módulo permite:

- gerar fatura a partir da versão contratual aplicável à competência;
- emitir, enviar, reenviar, cancelar ou substituir uma fatura;
- registrar mensalidade, adicionais, desconto, crédito, impostos e total;
- consultar vencimento, saldo, documento fiscal e histórico de entrega;
- filtrar por período, organização, plano e estado;
- exportar a visão financeira sem incluir dados operacionais do tenant.

Cada item da fatura preserva o snapshot de descrição, quantidade, valor unitário,
desconto e versão contratual. A alteração posterior do plano não muda o documento
emitido.

Estado entregue na Fase 2: geração mensal para assinaturas `ACTIVE`, emissão
`DRAFT → OPEN`, anulação `OPEN → VOID`, listagem paginada, detalhe e exportação
CSV. Pagamento parcial/total e vencimento derivado foram entregues na Fase 3.
Envio, substituição e emissão fiscal dependem de provider real; não são
simulados.

### 3.5 Recebimentos e conciliação SaaS

O módulo registra pagamentos destinados à Dashem e suas alocações em faturas.
Deve suportar:

- confirmação automática por webhook autenticado do provider;
- consulta de transação em estado desconhecido antes de nova tentativa;
- recebimento total ou parcial;
- uma confirmação alocada em uma ou mais faturas;
- estorno como fato compensatório, sem apagar o recebimento original;
- conciliação entre fatura, transação do provider e valor liquidado;
- registro manual somente com motivo, evidência e auditoria.

Uma venda paga no PDV do tenant nunca é um recebimento do SaaS.

Estado entregue na Fase 3: ledger provider-neutral persistido, baixa manual com
evidência e AAL2, webhook HMAC fail-closed, idempotência, conciliação explícita
de `UNKNOWN`, alocação parcial/total e estorno compensatório imutável. A
automação externa só pode ser ativada depois da escolha e configuração de um
provider real.

### 3.6 Inadimplência e cobrança

Uma fatura aberta ultrapassando o vencimento torna-se vencida por processo
server-side idempotente. O módulo permite:

- régua configurável de lembretes antes e depois do vencimento;
- histórico de e-mail, mensagem, contato manual e resultado;
- registro de promessa de pagamento e observação interna;
- filtros por faixa de atraso e valor;
- renegociação ou crédito com autorização explícita;
- política de pausa/suspensão contratual separada do estado da fatura.

Inadimplência não suspende silenciosamente o tenant. Qualquer impacto no ciclo de
vida da assinatura exige política configurada, ação auditada e comunicação. A
fatura continua sendo preservada como fato financeiro.

Estado entregue na Fase 3: derivação idempotente de `OVERDUE` por saldo e data
de corte e histórico append-only de ações de cobrança. Envio automático de
mensagens e política de suspensão continuam desativados enquanto não houver
transporte e regra comercial configurados.

### 3.7 Configuração

Configurações do módulo:

- moeda inicial `BRL`;
- timezone financeiro `America/Sao_Paulo`;
- numeração e série de faturas;
- dias permitidos para vencimento;
- regras de pró-rata e arredondamento;
- régua de cobrança;
- provider de pagamento e credenciais por secret manager;
- emissão fiscal da Dashem;
- templates de comunicação;
- retenção e exportação de registros.

Credenciais e segredos nunca são retornados pela API ou gravados em auditoria.

## 4. Definições canônicas dos indicadores

Os indicadores usam valores monetários decimais e uma competência explícita.

| Indicador | Definição |
| --- | --- |
| MRR | Soma do valor recorrente mensal normalizado das assinaturas comerciais vigentes no último dia do período. Trial gratuito e assinatura cancelada não entram. Assinatura inadimplente continua no MRR até cancelamento ou encerramento contratual. |
| ARR | `MRR × 12`; projeção, não caixa recebido. |
| Novo MRR | MRR de assinaturas que se tornaram pagas no período. |
| Expansão de MRR | Aumento recorrente por upgrade ou adicional contratado. |
| Contração de MRR | Redução recorrente sem encerramento da assinatura. |
| Churned MRR | MRR perdido por cancelamento ou encerramento no período. |
| Net New MRR | `novo + expansão - contração - churned`. |
| Logo churn | Organizações pagantes encerradas ÷ organizações pagantes no início do período. |
| Valor faturado | Total de faturas SaaS emitidas no período, líquido de documentos cancelados e créditos aplicáveis. |
| Valor recebido | Soma das alocações de recebimentos confirmados no período, líquida de estornos. |
| Saldo em aberto | Total emitido menos recebimentos e créditos alocados. |
| Saldo vencido | Parcela do saldo em aberto com vencimento anterior à data de corte. |
| Taxa de recebimento | Valor recebido aplicável ÷ valor vencido no período; fórmula e corte aparecem na interface. |
| Taxa de inadimplência | Saldo vencido ÷ saldo total vencido até a data de corte. |

MRR não é faturamento do tenant, valor faturado não é MRR e recebimento não é
sinônimo de emissão. A interface deve preservar esses nomes e diferenças.

## 5. Estados de domínio

### 5.1 Assinatura

```text
PENDING → TRIAL → ACTIVE → PAUSED → ACTIVE
                    └────→ CANCELED → ENDED
```

- `PENDING`: contratação incompleta ou ainda não iniciada;
- `TRIAL`: avaliação com data de término;
- `ACTIVE`: contrato comercial vigente;
- `PAUSED`: acesso comercial temporariamente pausado por ação explícita;
- `CANCELED`: cancelamento solicitado ou efetivado, com data de efeito;
- `ENDED`: obrigação recorrente encerrada.

O estado da assinatura não deve ser usado para representar pagamento de uma
fatura. Situação contratual e situação financeira são eixos separados.

### 5.2 Fatura

```text
DRAFT → OPEN → PARTIALLY_PAID → PAID
          ├──→ OVERDUE ───────→ PAID
          ├──→ VOID
          └──→ UNCOLLECTIBLE
```

- `DRAFT` pode ser recalculada antes da emissão;
- `OPEN` é um documento emitido com saldo integral;
- `PARTIALLY_PAID` possui alocação confirmada menor que o total;
- `PAID` possui saldo zero por recebimento ou crédito válido;
- `OVERDUE` possui saldo após o vencimento;
- `VOID` foi cancelada sem recebimento válido;
- `UNCOLLECTIBLE` preserva a dívida reconhecida como não recuperável.

Na Fase 2 somente `DRAFT`, `OPEN` e `VOID` possuem comandos. Os demais estados
estão reservados no modelo e só poderão ser produzidos pelos fatos de pagamento,
saldo e vencimento da Fase 3.

### 5.3 Pagamento SaaS

```text
PENDING → PROCESSING → SUCCEEDED
                 ├──→ FAILED
                 └──→ UNKNOWN → consulta/reconciliação
SUCCEEDED → PARTIALLY_REFUNDED → REFUNDED
```

Somente `SUCCEEDED` reduz saldo. `UNKNOWN` nunca autoriza criar uma segunda
cobrança sem consulta idempotente ao provider.

## 6. Modelo técnico

### 6.1 Contexto e propriedade

O contexto técnico sugerido é `owner_finance`, separado dos módulos `sales`,
`cash`, `payments`, `receivables`, `fiscal` e `bi` pertencentes aos tenants.

As tabelas do Owner Financeiro são **platform-owned**. O `tenant_id` identifica
o cliente contratante, mas não transforma o registro em dado operacional do
tenant. O acesso exige escopo de plataforma e RBAC do Control; usuários do
tenant não recebem acesso por herança.

É proibido ao serviço `owner_finance` depender de modelos ou repositórios de:

```text
Sale, Order, CashSession, Payment do PDV, Receivable do tenant,
InventoryBalance, BiDailyFact ou memberships operacionais
```

### 6.2 Agregados

#### `SaasBillingAccount`

- `id`;
- `tenant_id`, único;
- dados cadastrais e fiscais de cobrança;
- contato de cobrança;
- `currency`;
- `provider_customer_reference` tokenizada;
- `created_at`, `updated_at`.

#### `TenantSubscription`

O agregado existente continua sendo a raiz da assinatura comercial e deve ser
evoluído sem criar uma segunda fonte de verdade:

- `tenant_id`, `plan_id` e versão contratual vigente;
- estado e datas de início, trial, cancelamento e encerramento;
- valor recorrente, dia de vencimento e próxima competência;
- política de cobrança aplicável;
- desconto recorrente e período de vigência, quando houver;
- versão concorrente para atualização otimista.

O antigo campo textual `billing_status` foi removido na migration
`050_saas_finance_foundation`: ele permitia declarar `CURRENT` ou `OVERDUE` sem
uma fatura que comprovasse o estado. Situação financeira será derivada das
faturas, evitando divergência editável manualmente.

#### `SaasInvoice`

- identificador interno e número público único;
- `billing_account_id`, `tenant_id`, `subscription_id`;
- início e fim da competência;
- datas de emissão e vencimento;
- moeda, subtotal, desconto, impostos, total, saldo;
- estado;
- referência fiscal e referência externa do provider;
- chave de idempotência da competência;
- timestamps de emissão, pagamento, cancelamento e atualização;
- `version` para concorrência otimista.

Implementação: `backend/app/models/owner_finance.py`, migrations
`052_saas_invoicing` e `054_saas_receipts_collections`. Emissão, anulação,
recebimento, estorno e cobrança guardam ator, motivo/evidência, chave de
idempotência e hash da requisição no agregado platform-owned, sem usar o
repositório de idempotência operacional dos tenants.

Restrição mínima: uma fatura recorrente por assinatura, competência e versão de
reprocessamento. Repetir o job não duplica documento.

#### `SaasInvoiceLine`

- `invoice_id`;
- tipo: `PLAN`, `CAPABILITY`, `ADD_ON`, `DISCOUNT`, `CREDIT`, `TAX` ou
  `ADJUSTMENT`;
- snapshot da descrição;
- quantidade, valor unitário e total;
- referência à versão contratual de origem.

#### `SaasPayment`

- `billing_account_id` e `tenant_id`;
- provider, referência externa e chave de idempotência;
- estado, moeda e valor;
- meio de pagamento sanitizado;
- código de falha sanitizado;
- timestamps do ciclo e versão concorrente.

#### `SaasPaymentAllocation`

- `payment_id`, `invoice_id`;
- valor alocado;
- timestamp e chave idempotente.

A soma das alocações confirmadas não pode superar o pagamento nem o saldo das
faturas sem um crédito explícito.

#### `SaasRefund`

- `payment_id`;
- valor, motivo e estado;
- referência externa;
- ator, aprovação e timestamps.

#### `SaasCollectionEvent`

- `invoice_id` e `tenant_id`;
- tipo, canal e resultado;
- destinatário mascarado;
- detalhe sanitizado e referência do provider;
- ator ou job de origem;
- timestamp e chave idempotente.

#### `SaasFinanceDailyMetric`

Projeção reconstruível por competência contendo apenas fatos do SaaS. Guarda
versão de fórmula, watermark e horário de cálculo. Não recebe colunas vindas de
vendas, caixa, equipe, estoque ou BI do tenant.

### 6.3 Autoridade monetária

- valores usam `Numeric`, nunca ponto flutuante;
- o backend calcula total, saldo, impostos, desconto e pró-rata;
- a UI não envia um total autoritativo;
- faturas emitidas e pagamentos confirmados são imutáveis;
- correções usam crédito, estorno, substituição ou evento compensatório;
- toda mutação aceita chave de idempotência;
- jobs usam lock por assinatura e competência;
- concorrência de pagamento é serializada antes da alocação;
- timestamps são armazenados em UTC e apresentados no timezone financeiro.

### 6.4 API canônica

Base canônica:

```text
/api/v1/control/finance
```

Consultas implementadas nas Fases 2 e 3:

```text
GET /invoices
GET /invoices/{invoice_id}
GET /invoices/export
GET /payments
GET /payments/{payment_id}
GET /collections/events
```

Comandos implementados nas Fases 2 e 3:

```text
POST /invoices/generate
POST /invoices/{invoice_id}/issue
POST /invoices/{invoice_id}/void
POST /payments/manual
POST /payments/{payment_id}/reconcile
POST /payments/{payment_id}/refunds
POST /collections/mark-overdue
POST /collections/events
```

O overview contratual permanece em
`GET /api/v1/identity/platform/finance/overview` e a conta de cobrança em
`PUT /api/v1/identity/platform/finance/billing-accounts/{tenant_id}`. O ingresso
externo está em `POST /api/v1/control/finance/provider/webhooks/{provider}` e
permanece fail-closed sem configuração. Rotas de projeção continuam previstas
para a Fase 4 e não existem como stubs que retornam sucesso.

Webhooks de provider ficam em rota própria, validam assinatura, persistem o
payload mínimo sanitizado e entregam o comando ao domínio com idempotência.

Listagens são paginadas e filtradas no servidor. Exportações grandes são jobs
assíncronos com arquivo temporário, expiração e auditoria.

### 6.5 Autorização

Permissões mínimas:

- `control.finance.read`;
- `control.finance.manage_billing`;
- `control.finance.collect`;
- `control.finance.reconcile`;
- `control.finance.refund`;
- `control.finance.export`;
- `control.finance.configure`.

`PLATFORM_OWNER` pode receber todas. Um futuro papel `FINANCE` deve receber
somente as permissões financeiras necessárias. `AUDITOR` possui leitura sem
segredos e sem comandos. `SALES`, `SUPPORT` e `OPERATIONS` não recebem acesso
financeiro por padrão.

Matriz inicial implementada na migration `051_platform_finance_permissions`:

| Papel | Permissões financeiras padrão |
|---|---|
| `PLATFORM_OWNER` | todas as sete permissões |
| `PLATFORM_ADMIN` | leitura, conta de cobrança, cobrança, conciliação, exportação e configuração; sem estorno |
| `AUDITOR` | somente `control.finance.read` |
| `SALES`, `SUPPORT`, `OPERATIONS` | nenhuma |

Os padrões ficam persistidos em `platform_role_permissions`. Uma concessão ou
negação individual em `platform_permission_grants` prevalece sobre o papel;
permissão ausente é negada. As três tabelas de autorização usam RLS
`platform-only`.

Comandos financeiros exigem AAL2. Estorno, baixa manual, crédito e cancelamento
exigem motivo; valores acima de limite configurado podem exigir segunda
aprovação.

### 6.6 Auditoria e eventos

Toda mutação grava auditoria e outbox na mesma transação. Eventos mínimos:

- `saas.subscription.changed`;
- `saas.invoice.generated`;
- `saas.invoice.issued`;
- `saas.invoice.voided`;
- `saas.invoice.overdue`;
- `saas.payment.processing`;
- `saas.payment.succeeded`;
- `saas.payment.failed`;
- `saas.payment.refunded`;
- `saas.collection.recorded`;
- `saas.subscription.canceled`.

Auditoria guarda ator, ação, alvo, motivo, correlação, valores anteriores e
novos permitidos. Não guarda cartão completo, credencial, token, segredo ou
payload bruto de provider.

### 6.7 Jobs

- geração de faturas por competência;
- marcação de vencimento;
- consulta de pagamentos `UNKNOWN`;
- execução da régua de cobrança;
- reconstrução das projeções diárias;
- conciliação periódica com o provider;
- retenção e expiração de exportações.

Jobs são reentrantes, idempotentes, observáveis e não presumem sucesso sem
evidência externa.

## 7. Ajuste obrigatório da Saúde da Plataforma

A implementação atual deve ser corrigida para retirar do Control os totais de
unidades ativas, usuários ativos e caixas abertos, além da consulta de métricas
operacionais por tenant.

A página **Saúde da plataforma** deve conter somente:

- estado e latência da API e do banco;
- autenticação e entrega de e-mail;
- heartbeat de workers;
- backlog e falhas técnicas de outbox;
- estado das integrações da plataforma;
- incidentes, última verificação e erro sanitizado;
- quantidade de organizações por estado comercial, quando útil ao Control.

O endpoint de saúde não deve importar nem consultar `CashSession`, `Sale`,
`Payment`, `InventoryBalance` ou contagens de memberships operacionais. A API de
métricas por tenant deve ser removida do Control ou substituída por um resumo
estritamente contratual, de onboarding e de suporte.

## 8. Migração a partir do estado atual

### Fase 0 — corrigir a fronteira

Estado: **concluída no primeiro sprint do S18.1**.

- remover da UI do Control cards de unidades ativas, usuários ativos e caixas
  abertos;
- remover do endpoint de saúde as consultas correspondentes;
- descontinuar métricas de vendas, receita, produtos, estoque, caixas e equipe
  por tenant no escopo de plataforma;
- manter essas métricas apenas no Dashem Gestão, com autorização do tenant;
- adicionar teste arquitetural que impeça dependência entre `owner_finance` e
  módulos operacionais do tenant.

### Fase 1 — fundação comercial

Estado em 28 de agosto de 2026: **concluída**. A projeção contratual, a
navegação **Financeiro SaaS**, o endpoint
`GET /api/v1/identity/platform/finance/overview`, a conta de cobrança
platform-owned, a autorização `control.finance.*` e o versionamento concorrente
estão implementados. O antigo status financeiro manual foi removido. Estado de
adimplência será criado somente quando houver fatos de fatura.

- [x] consolidar conta de cobrança e assinatura existentes;
- [x] versionar alterações concorrentes do contrato;
- [x] separar estado contratual de futuro estado derivado das faturas;
- [x] criar permissões financeiras granulares;
- [x] concluir auditoria dedicada da conta de cobrança;
- [x] disponibilizar a aba **Conta de cobrança** com `expected_version` e
  conflito `409`;
- [x] exigir `expected_billing_account_version` no contrato para impedir
  sobrescrita concorrente entre os dois editores;
- [x] gravar `platform.finance.billing_account_updated` em auditoria e outbox na
  mesma transação.

Endpoint implementado nesta fase:

```text
PUT /api/v1/identity/platform/finance/billing-accounts/{tenant_id}
```

Ele aceita somente cadastro fiscal e contato de cobrança da assinatura Dashem.
Não aceita status de fatura, adimplência, pagamento ou qualquer dado
operacional do tenant.

### Enforcement dos limites comerciais

Os limites de usuários, dispositivos e unidades escolhidos dentro do teto do
plano são copiados para uma projeção tenant-readable da assinatura e validados
no backend no momento da criação de cada recurso. A verificação ocorre dentro
do tenant e não publica contagens de uso para o Owner.

O limite de storage permanece apenas como dado contratual de compatibilidade.
Como ainda não existe medidor canônico de bytes/objetos, ele não deve ser
descrito como bloqueio efetivo nem usado como indicador de saúde até a entrega
da medição correspondente.

As abas **Plano e cobrança**, **Modelos de negócio**, **Capabilities** e
**Limites** devem permanecer visíveis mesmo quando o catálogo não possui plano.
A ausência de plano bloqueia somente o salvamento da nova versão contratual;
ela nunca pode substituir ou esconder o editor já construído.

### Fase 2 — faturamento SaaS

Estado em 28 de agosto de 2026: **concluída no escopo persistido e sem provider
fiscal configurado**.

- [x] criar faturas e itens platform-owned com snapshots;
- [x] implementar geração por competência e idempotência;
- [x] proteger unicidade por assinatura, competência e revisão;
- [x] entregar `DRAFT → OPEN → VOID`, motivo, AAL2, versão concorrente e
  idempotência;
- [x] impedir alteração do snapshot e dos itens após emissão por trigger no
  PostgreSQL;
- [x] entregar listagem paginada, detalhe e exportação CSV;
- [x] liberar cards reais de valor emitido, saldo aberto, rascunhos e anulações;
- [x] manter recebimento e inadimplência como **Em implementação**;
- [ ] integrar emissão fiscal da própria Dashem quando um provider real for
  selecionado e configurado; até lá nenhuma emissão é declarada.

### Fase 3 — recebimentos e cobrança

Estado em 29 de agosto de 2026: **concluída no escopo provider-neutral e
persistido**.

- [x] persistir pagamentos, alocações, estornos e eventos de cobrança;
- [x] aceitar webhook HMAC somente com segredo e identidade técnica;
- [x] garantir idempotência externa e rejeitar replays divergentes;
- [x] conciliar resultados `UNKNOWN` antes de alocar valor;
- [x] derivar recebimento parcial/total, saldo, pagamento e vencimento;
- [x] registrar baixa manual, estorno e cobrança com AAL2, evidência e auditoria;
- [ ] escolher e configurar provider comercial real e sua consulta automática;
- [ ] configurar transporte e política real para mensagens da régua de cobrança.

### Fase 4 — saúde financeira

- materializar MRR, ARR, movimentos de MRR, churn e inadimplência;
- fornecer drill-down até os fatos SaaS;
- validar fórmulas contra conjuntos fechados de faturas e assinaturas;
- apresentar atraso, watermark e versão da projeção.

## 9. Critérios de aceite

### 9.1 Fronteira e privacidade

- nenhum endpoint do Control retorna vendas, faturamento, lucro, caixas,
  estoque, clientes finais ou quadro de funcionários do tenant;
- a Saúde da Plataforma não exibe usuários ativos, unidades em operação ou
  caixas abertos;
- o Owner Financeiro não consulta tabelas operacionais do tenant;
- o Gestor do tenant continua visualizando suas métricas somente no Dashem
  Gestão, segundo permissões próprias;
- capabilities mostradas no Control são as contratadas, não inferências do uso.

### 9.2 Faturamento e recebimento

- repetir a geração da mesma competência não duplica fatura;
- alterar plano não reescreve fatura emitida;
- pagamento confirmado reduz saldo uma única vez;
- webhook repetido não duplica pagamento ou alocação;
- estado `UNKNOWN` é consultado antes de nova cobrança;
- pagamento parcial preserva saldo restante;
- estorno cria fato compensatório;
- baixa manual exige AAL2, motivo, evidência e auditoria.

### 9.3 Indicadores

- cada card possui fórmula documentada e drill-down;
- MRR é calculado apenas sobre assinaturas da Dashem;
- recebimento é calculado apenas sobre pagamentos das faturas SaaS;
- nenhuma fórmula usa `Sale`, `CashSession`, pagamentos do PDV ou BI do tenant;
- projeções informam competência, watermark e versão da fórmula;
- reconstruir a projeção produz o mesmo resultado para os mesmos fatos.

### 9.4 Segurança e operação

- tenant user não acessa `/api/v1/control/finance`;
- papéis de plataforma respeitam as permissões financeiras;
- comandos sensíveis exigem AAL2;
- segredos e dados completos do meio de pagamento não aparecem em logs,
  respostas ou auditoria;
- migrations, downgrade/rebuild, testes de autorização e concorrência passam;
- falha externa aparece como falha ou não instrumentada, nunca como sucesso
  presumido.

## 10. Fora de escopo

- contabilidade geral completa da Dashem;
- folha de pagamento e gestão de funcionários da Dashem;
- contas a pagar e compras internas da Dashem;
- planejamento orçamentário e fluxo de caixa corporativo;
- faturamento, lucro, caixa, fiscal, recebíveis ou BI dos tenants;
- cobrança de clientes finais dos tenants;
- precificação automática baseada no volume de vendas do tenant;
- telemetria de comportamento operacional usada como fonte de cobrança.

Esses itens exigem contextos próprios. O Owner Financeiro V1 é um módulo de
**receita recorrente e cobrança do SaaS**, não um ERP contábil nem uma janela
sobre o negócio dos clientes.

## 11. Definição de pronto

O módulo está pronto quando a Dashem consegue explicar e rastrear sua receita
recorrente desde o contrato até a fatura e o recebimento, operar atrasos com
segurança e reconstruir os indicadores financeiros, sem consultar ou revelar a
operação comercial de nenhum tenant.
