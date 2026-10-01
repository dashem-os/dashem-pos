# Ponto de retomada — Channel Hub S10.1 — 29/09/2026

Este registro atualiza a [pausa técnica de 16/09](pausa-tecnica-2026-09-16.md).
Não declara o S10.1 encerrado nem homologação de um canal comercial.

## Estado conferido

- `HEAD` e `origin/main` estão em `1692796`; as alterações D1/R11 permanecem
  somente na árvore de trabalho. O CI desse commit foi informado pelo executor
  como verde nos quatro jobs; esta revisão não consultou os logs remotos.
- A travessia autenticada local R20 com gestora e leitora e a medição R14 estão
  registradas na [proposta S10.1](proposta-s10-1-channel-hub.md). R14 é prova
  interna com conector de referência, não SLA nem homologação externa.
- O dono decidiu D1: o pedido externo usa o valor declarado pelo canal, preserva
  a oferta local e sua diferença, sem alterar o catálogo do restaurante.
- O agente preparou localmente a migração `101_the_channel_price_stands` e código
  para D1/R11. **Não há commit nem push dessa fatia; a migração 101 não foi
  publicada.** A árvore de trabalho contém as alterações do agente e este
  registro documental.
- O agente informou 51 testes do Channel Hub, 31 testes arquiteturais e de
  domínio, 204 testes de frontend, build, downgrade/upgrade e `alembic check`
  verdes contra PostgreSQL isolado. Esta revisão examinou código e testes, mas
  não reexecutou essas suítes. O relatório chama isso de portão local completo,
  mas lista apenas 82 testes de backend selecionados; não há resultado da suíte
  completa do backend para esta fatia nem CI do código D1/R11.

## Revisão ainda aberta para D1/R11

O código já preserva preço de linha, desconto, taxa, subsídio informativo e
diferença para a oferta local. A negociação calcula itens menos desconto de
cabeçalho mais entrega, e recusa negociação de pedido identificado como pago
no marketplace. A atualização que reduziria o total abaixo de uma reserva ou
liquidação testada vai para `NEEDS_REVIEW`.

Três casos ainda exigem correção e prova antes de publicar:

1. O conector de referência transforma qualquer status diferente de
   `PAID_ONLINE`, inclusive status ausente ou desconhecido, em
   `payment_origin=None`. A negociação aceita esse valor como pagável
   localmente. Cobrança local deve exigir indicação explícita de pagamento
   local, sem inferi-la da ausência de informação.
2. Uma atualização pode mudar `payment_origin` de local/indefinido para
   `MARKETPLACE` enquanto existe reserva ou liquidação local, sem alterar os
   valores. A verificação atual só compara a nova obrigação com a cobertura;
   ela não bloqueia essa mudança de origem. O resultado pode deixar pagamento
   local em voo junto com uma declaração de pagamento no canal.
3. Em `_order_amount`, o retorno antecipado quando a soma dos itens é zero
   ignora uma taxa de entrega positiva. Um pedido gratuito com entrega deve
   conservar o total declarado do canal ou ir para revisão, conforme o contrato.

Também é preciso provar que a atribuição conservadora de alocações sem
`order_id` em negociações com vários pedidos não registra a mesma reserva como
valor pertencente a cada pedido. Até essa prova, o efeito é uma possível
pendência indevida, não uma cobrança comprovadamente errada.

## Próxima ação (registrada em 29/09/2026)

Corrigir os três casos, reproduzi-los em testes antes da correção e percorrer
de novo os testes afetados e a suíte completa do backend, além dos demais
portões locais. Depois revisar o diff completo,
publicar a migração 101 com o código no mesmo commit e conferir os quatro jobs
do CI. O gate final do S10.1 segue separado. D2, D8 e a concessão da D7 ainda
estão pendentes; purga e controle de backups/logs ainda não implementam a
política de retenção. iFood, 99Food e outros canais reais não foram integrados
nem homologados.

## Resolução e evidências em 30/09/2026 (aguardando revisão antes de commit/push)

As quatro frentes abertas neste ponto de retomada foram corrigidas e provadas na
árvore local sobre `1692796`, sem `commit` nem `push`:

1. **Pagamento local explícito vs. informação desconhecida (`contracts.py`,
   `adapters/reference.py`, `orders.py`, `negotiation_service.py`):**
   - `ExternalPaymentOrigin` distingue `MARKETPLACE` (`PAID_ONLINE`), `LOCAL`
     explicitamente declarado (`PAY_ON_DELIVERY`, `PAY_AT_COUNTER`, `LOCAL`) e
     `UNKNOWN` (status ausente ou não reconhecido; padrão de `ExternalOrder`).
   - `negotiation_service._refuse_if_paid_in_marketplace()` (chamado em
     `open_negotiation()` e `reconcile_source()`) exige `payment_origin == "LOCAL"`
     para cobrança local, recusando `MARKETPLACE` com `409 ORDER_PAID_IN_MARKETPLACE`
     e informação insuficiente (`UNKNOWN`, pedido legado com `payment_origin = None`
     ou pedido sem linha em `external_order_mappings`) com
     `409 ORDER_PAYMENT_ORIGIN_UNKNOWN`.
   - Provado em `test_channel_contract.py::test_payment_origin_distinguishes_marketplace_explicit_local_and_unknown`
     e `test_channel_inbox.py::test_r11_protege_pedido_marketplace_contra_cobranca_local_e_bloqueia_desconto_de_cabecalho_sob_reserva`.
2. **Proteção da mudança de origem com dinheiro local em curso ou liquidado
   (`channels/orders.py`, `channels/inbox.py`):**
   - Em `orders._update()`, quando o pedido possui cobertura local (`PENDING` /
     `PROCESSING` ou `CONFIRMED` / recebível) e um `ORDER_UPDATED` tenta mudar
     `payment_origin` para fora de `LOCAL` (ex.: `MARKETPLACE` ou `UNKNOWN`),
     mesmo mantendo todos os valores monetários idênticos, o evento vai para
     `NEEDS_REVIEW` com código `CHANNEL_PAYMENT_ORIGIN_CONFLICT`, revertendo a
     transação de aplicação sem alteração parcial de pedido, itens, mapeamento ou
     alocações e sem cancelar nem confirmar automaticamente pagamentos em voo.
   - Sem cobertura local, a transição de `LOCAL` para `MARKETPLACE` aplica
     normalmente (`APPLIED`) e passa a recusar negociação local futura com
     `ORDER_PAID_IN_MARKETPLACE`.
   - Provado com reserva `PENDING`, com liquidação `CONFIRMED` e sem cobertura
     local em `test_channel_inbox.py::test_r11_bloqueia_mudanca_de_origem_com_dinheiro_local_em_curso_ou_liquidado_e_permite_sem_cobertura`.
3. **Total de pedido com itens ativos gratuitos vs. pedido cancelado ou sem itens
   ativos (`negotiation_service.py`):**
   - `_order_amount()` retorna `Decimal("0.0000")` apenas quando
     `order.status == OrderStatusEnum.CANCELED` ou quando não há itens ativos
     (`not items`). Quando existem itens ativos cuja mercadoria líquida é
     `R$ 0,00` (`unit_price = 0.00` ou desconto igual aos itens) e
     `delivery_fee = R$ 7,00`, `_order_amount()` preserva a obrigação de
     `R$ 7,0000`.
   - Provado nos dois sentidos em
     `test_channel_inbox.py::test_r11_itens_ativos_gratuitos_conservam_entrega_e_pedido_cancelado_ou_sem_itens_ativos_retorna_zero`.
4. **Cobertura em negociações com vários pedidos (`settlement/contracts.py`,
   `negotiation_service.py`, `channels/orders.py`, `transfer_service.py`):**
   - `settlement.hold_on_orders()` retorna exclusivamente as alocações atribuídas
     a cada pedido (`PaymentAllocation.order_id == order.id`), deixando de somar
     alocações sem `order_id` e `ReceivableAllocation` da negociação inteira em
     cada pedido vinculado.
   - `settlement.coverage_on_orders()` expõe `OrderCoverage` (`order_covered`,
     `unassigned_covered`, `joint_covered`, `other_orders_amount`,
     `negotiation_adjustments`) sem inventar rateio entre pedidos: alterações que
     respeitam tanto `order_covered` quanto `joint_covered` são aplicadas e
     reconciliadas, enquanto reduções abaixo da cobertura atribuída ao pedido ou
     abaixo da cobertura conjunta da negociação vão para `NEEDS_REVIEW`
     (`ITEM_BELOW_SETTLEMENT`).
   - `transfer_service._order_has_coverage()` consulta tanto `hold_on_orders`
     quanto `coverage_on_orders` para continuar impedindo transferência de
     comanda coberta por alocação não atribuída ou recebível na negociação.
    - Provado com dois pedidos e alocações atribuídas e não atribuídas em
      `test_channel_inbox.py::test_r11_cobertura_em_negociacao_com_varios_pedidos_separa_cobertura_do_pedido_da_cobertura_conjunta`.
5. **Proteção de cancelamento (`ORDER_CANCELLED` e `cancel_external_order`) sob
   cobertura atribuída e cobertura conjunta (`channels/orders.py`,
   `order_service.py`):**
   - `ORDER_CANCELLED` em `channels/orders.py` e `order_service.cancel_external_order()`
     passaram a consultar `settlement.hold_on_orders()` e
     `settlement.coverage_on_orders()` além de `hold_on_items()`: quando há
     cobertura atribuída ao pedido (`order_covered > 0`, incluindo intenção `PIX`
     `PENDING` com `allocations=[]` em negociação de pedido único ou intenção
     `CONFIRMED` / recebível) ou quando zerar o pedido reduziria a obrigação
     conjunta da negociação abaixo de `joint_covered`
     (`coverage.joint_total_with(0) < coverage.joint_covered`), o cancelamento é
     encaminhado para `NEEDS_REVIEW` (`ITEM_BELOW_SETTLEMENT`), preservando
     atomicamente `Order`, `OrderItem`, `ChannelOrderLine`, `ExternalOrderMapping`
     e `PaymentAllocation`.
   - O cancelamento de pedido sem cobertura continua retornando `APPLIED`,
     levando `Order` e `ChannelOrderLine` para `CANCELED` e `_order_amount()`
     para `R$ 0,0000`.
   - Provado em
     `test_channel_inbox.py::test_r11_cancelamento_respeita_cobertura_atribuida_e_conjunta_sem_bloquear_cancelamento_sem_cobertura`.
6. **Garantia transacional comum sob concorrência e hierarquia canônica de
   bloqueios (`negotiation_service.py`, `channels/orders.py`):**
   - `_lock_coverage_scope(session, order_ids)` (invocado por
     `_coverage_on_orders()`) adquire `SELECT ... FOR UPDATE` com
     `execution_options(populate_existing=True)` em ordem determinística por `id`
     sobre todas as `CheckoutNegotiation` vinculadas e, em seguida, sobre todos os
     `Order` vinculados a essas negociações (com rechecagem de vínculos recém-criados
     antes do bloqueio de `Order`).
   - Foi unificada a hierarquia de bloqueios entre processamento de canais
     (`orders.apply` / `_update`), abertura/reconciliação de negociação
     (`open_negotiation` / `reconcile_source`) e criação/confirmação de intenção
     de pagamento (`create_intent` / `confirm_intent`):
     `PaymentIntent` $\rightarrow$ `CheckoutNegotiation (ORDER BY id)`
     $\rightarrow$ `Order (ORDER BY id)` $\rightarrow$ `ExternalOrderMapping`
     $\rightarrow$ `OrderItem (ORDER BY id)`.
   - Leituras de `_order_amount()`, `_channel_order_terms()` e `_lines()` usam
     `populate_existing=True` para não reutilizar estado obsoleto do identity map
     da `Session` após aguardar o bloqueio concorrente, e `_source_version()`
     soma os timestamps em microssegundos de todos os pedidos vinculados para que
     a atualização de qualquer pedido avance `source_version`.
   - Provado deterministicamente com `threading.Barrier` em
     `test_channel_inbox.py::test_r11_protecao_conjunta_sob_concorrencia_deterministica_serializa_reducoes_e_preserva_cobertura`
     (dois pedidos `LOCAL` de `R$ 100,00` na mesma negociação com reserva não
     atribuída de `R$ 150,00` e dois `ORDER_UPDATED` concorrentes reduzindo cada
     pedido para `R$ 60,00`: exatamente um é `APPLIED` e o outro vai para
     `NEEDS_REVIEW` com `ITEM_BELOW_SETTLEMENT`, preservando total conjunto de
     `R$ 160,00 >= R$ 150,00`).

### Verificações executadas em 30/09/2026 (PostgreSQL 15 isolado `dashem_s101_gate_db`)

- **Ambiente Python / SQLModel:** Python `3.11.15`, `sqlmodel 0.0.42` (alinhado ao CI).
- **Higiene de diff:** `git diff --check` → `0` avisos de espaço em branco ou fim de arquivo.
- **Alembic (`100_the_notice_leaves <-> 101_the_channel_price_stands`):**
  `python -m alembic current`, `python -m alembic downgrade 100`,
  `python -m alembic upgrade head` e `python -m alembic check` →
  `No new upgrade operations detected.`
- **Testes selecionados — Channel Hub (7 arquivos):**
  `python -m pytest tests/test_channel_contract.py tests/test_channel_ingress.py tests/test_channel_inbox.py tests/test_channel_outbound.py tests/test_channel_screen_facts.py tests/test_s10_channel_hub.py tests/test_s13_channel_catalog_reconciliation.py -v`
  → **`68 passed` em `64.53s`**.
- **Testes selecionados — fronteiras arquiteturais, guarda de logs e domínios financeiros:**
  `python -m pytest tests/test_module_boundaries.py tests/test_no_personal_data_in_logs.py tests/test_s8_checkout_negotiation.py tests/test_s12_transfers.py tests/test_s14_receivables.py tests/test_s25_item_settlement.py tests/test_s25_live_settlement.py -v`
  → **`24 passed` em `37.95s`**.
- **Suíte completa do backend:**
  `python -m pytest tests -q` (com API de teste em `127.0.0.1:8002` `AUTH_MODE=disabled` e `127.0.0.1:8004` `AUTH_MODE=test`)
  → **`713 passed, 1 skipped, 1 xfailed` em `459.85s` (0 falhas)**.
- **Frontend (testes, typecheck e build):**
  `npm test` → **`204 pass, 0 fail`**; `npm run build` (`tsc && vite build`) → **build concluído em `12.48s`**.

## Resolução da concorrência de comanda e atividades locais em 01/10/2026

O revisor identificou uma inversão pontual de bloqueios em seis combinações:
`add_item` / `update_item` / `cancel_item` $\times$ `create_intent` / `confirm_intent`.
Nos comandos locais, as mutações em `Order` e `OrderItem` ocorriam antes da chamada
a `touch_session_activity`, provocando autoflush do ORM e bloqueio de `Order` antes de
`TableSession` (`Order` $\rightarrow$ `TableSession`). As operações financeiras seguiam
a ordem canônica (`TableSession` $\rightarrow$ `Order`), resultando em deadlocks `40P01`
em todos os seis casos reproduzidos em `.tmp/review_r11_table_activity.py`.

A correção delimitada foi aplicada e comprovada:

1. **Hierarquia canônica estendida:**
   - Nível 1: `PaymentIntent`
   - Nível 2: `CheckoutNegotiation (ORDER BY id)`
   - Nível 3: `TableSession (ORDER BY id)`
   - Nível 4: `ServiceTable (ORDER BY id)`
   - Nível 5: `Order (ORDER BY id)`
   - Nível 6: `ExternalOrderMapping (ORDER BY order_id)`
   - Nível 7: `OrderItem (ORDER BY id)`
2. **Preparação comum antecipada (`_prepare_item_mutation` em `order_service.py`):**
   - Executa antes de qualquer escrita de entidade, comando auditado ou operação que
     dispare autoflush;
   - Descobre `table_session_id`, adquire `TableSession FOR UPDATE` (Nível 3), `Order FOR UPDATE`
     (Nível 5) e `OrderItem FOR UPDATE` (Nível 7) com `populate_existing=True`;
   - Revalida tenant/unidade, integridade do vínculo `order.table_session_id`, status do pedido
     e do item;
   - Se o vínculo com a comanda tiver mudado durante a descoberta concorrente, descarta o savepoint
     (`session.begin_nested()`) e reinicia o protocolo com limite estrito de 5 tentativas;
   - Retorna as entidades bloqueadas para que os manipuladores não reconsultem ou adquiram
     bloqueios fora de ordem.
3. **Reutilização da sessão pré-bloqueada (`table_service.touch_session_activity`):**
   - Recebe `table_session` pré-bloqueado opcional; quando fornecido, avança `version`, `updated_at`
     e `last_activity_at` diretamente na instância já bloqueada, sem executar novo
     `SELECT ... FOR UPDATE` fora de ordem.
4. **Resultados e provas automatizadas:**
   - **Reprodutor do revisor (`review_r11_table_activity.py`):** todas as 6 combinações executadas
     contra PostgreSQL 15 isolado passaram sem deadlock (`native: completed`, `payment: completed`).
   - **Matriz de Concorrência (`backend/tests/test_r11_concurrency_matrix.py`):** 7 testes passaram
     em `32.98s`, incluindo `test_matrix_6_table_session_activity_vs_payment_canonical_ordering_and_control`
     cobrindo as 12 combinações (pagamento primeiro e comando local primeiro) e o controle negativo
     comprovando detecção determinística de `40P01` ao reintroduzir a inversão antiga.
   - **Suíte completa do backend:** `python -m pytest tests -q` com instâncias ativas em `8002` e `8004`
     → **`720 passed, 1 skipped, 1 xfailed` em `475.03s` (0 falhas)**.
   - **Alembic e Drift:** `alembic downgrade 100_the_notice_leaves`, `alembic upgrade head` e
     `alembic check` → `No new upgrade operations detected.`
   - **Frontend:** `npm test` (`204 pass, 0 fail`) e `npm run build` (`tsc && vite build`) concluído
     em `21.79s`.
   - **Higiene de diff:** `git diff --check` → `0` avisos de espaço em branco.

### Publicação em 01/10/2026 (commit `4b5e312`) e Separação de Evidências

- **Publicação:** fatia D1/R11 e migração 101 publicadas em `main` no commit `4b5e312`.
- **CI 36861234960 (GitHub Actions):** 4 jobs verdes (Alembic 54s, Backend 3m44s, Frontend 25s,
  Operational access E2E 1m21s).
- **Vercel:** deploy de produção confirmado para o commit `4b5e312` (Deployment `6784097052`,
  target `https://dashem-4veg3d7zz-dashem-09.vercel.app`, domínio `https://dashem-pos.vercel.app`
  HTTP 200).
- **Render:** API de produção saudável em `https://dashem-pos-api.onrender.com/health` (HTTP 200,
  `environment: production`).
- **Ressalva de produção:** o SHA exato do container em execução no Render e a execução da
  migração 101 no banco de produção permanecem **sem prova direta**, dada a ausência de acesso
  ou credenciais de introspecção direta ao banco e container de produção.

### Alinhamento Probatório e Estado do Gate (01/10/2026)

- **Publicação D1/R11 confirmada:** a migração 101 e a preservação de preços do canal permanecem aprovadas e publicadas (commits `4b5e312` e `9a6543c`, CI 36901102911 verde). Não reabrir sem regressão demonstrada.
- **Fechamento formal aguardando avaliação (GO pendente):** os testes e evidências foram estritamente alinhados nesta fatia delimitada ([gate consolidado](../quality/s10-1-gate-consolidado-2026-10-01.md)):
  1. R19: controle negativo de idempotência por linha (implementação normal passa; quebra deliberada de identificação estável provoca duplicação que faz a mesma verificação reprovar), conservando o teste de commit prematuro como controle de atomicidade;
  2. P8: comparação de snapshot de estado antes e depois da ingestão/atualização demonstrando ausência de criação ou alteração em CRM, fidelidade e fiscal;
  3. R20: evidência contendo `order_id` verificado na API e separação entre travessia visual e cenários de backend;
  4. D2/D8/D7: propostas mantidas como **NÃO APROVADAS para implementação**, com contradições sanadas (sem `OPEN` para tickets de produção, impactos financeiros segregados conforme iFood Financial API v2 e acesso de suporte temporário/auditado);
  5. S13.2: diagnóstico técnico ancorado nos modelos pré-existentes de `app/models/channel_catalog.py` (`ChannelCatalogOffer`, `ChannelPublicationBatch`, `ChannelPublicationItem`), definindo sua relação com snapshot imutável antes de qualquer início de codificação.
- **Pendências mantidas claramente:**
  1. Purga física (P12–P16): reservada para etapa posterior (§7, item 9), a ser executada após formalização de G2;
  2. D2 operacional: cancelamento em preparo segue retido no comportamento conservador comprovado (`NEEDS_REVIEW` com `PREPARATION_STARTED`), preservando produção e cobertura; esteira de resolução humana é proposta não aprovada;
  3. D8 avisos automáticos: proposta não aprovada; nenhuma emissão automática gerada antes de decisão;
  4. D7 concessões de perfis: proposta não aprovada; as 4 permissões constam no catálogo sem concessão a perfis padrão; acesso a contatos segue bloqueado até concessão explícita;
  5. Canais comerciais: nenhum canal real (iFood, 99Food) conectado; a fundação opera sobre o conector de referência.
