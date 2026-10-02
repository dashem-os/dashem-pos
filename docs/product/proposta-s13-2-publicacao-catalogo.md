# Proposta — S13.2: Publicação Fundacional de Catálogo no Channel Hub

Data: 02 de outubro de 2026<br>
Status: **S10.1 FECHADO E CONSOLIDADO; S13.2 FATIA FUNDACIONAL APROVADA EM COMMIT `f094468` (CI 36943602929 VERDE); FATIA API/UI CORRIGIDA COM RESOLUÇÃO INTEGRAL DOS BLOQUEIOS P1 A P4**<br>
Base: `f094468` em `main` (Sem novos commits locais, diffs prontos para inspeção).<br>
Migrações: `102_the_catalog_snapshot_freezes` (publicada) $\rightarrow$ `103_the_publication_batch_leases` (publicada e validada, sem nova migração).

---

## 1. Contexto, Escopo e Estado do Gate

O épico **S10.1** está **formalmente fechado e consolidado**:
- Provas R1 a R20 verdes no CI.
- **R19** comprovado com controle verdadeiro de idempotência por linha (mutante quebrado cria duplicação ativa preservando o original e reprova no detector comum; substituição legítima com dois ativos e um cancelado passa). O controle de commit prematuro permanece preservado como prova separada de atomicidade.
- **P8** comprovado com comparação estrita de snapshots antes e depois da ingestão em cenários com registros pré-existentes de CRM (`customers`), fidelidade/crédito e documentos fiscais, atestando ausência de efeitos colaterais.
- **R20** consolidado com a saída do roteiro final executado com autenticação real (`order_id: d7210e9a-5d54-4552-952b-be771d928fdc`), com separação formal entre a travessia visual da interface (Chopp R$ 18,50) e os cenários backend (−R$ 2,00 e −R$ 3,50 com complementos).

O épico **S13.2 (Catálogo e Integrações Avançadas)** estabelece a via reversa: a publicação controlada, versionada e idempotente do catálogo do DASHEM POS para canais de venda externos (marketplaces e e-commerce).

A aprovação formal da fatia fundacional ocorreu no commit `f094468`, ratificada pelo CI `36943602929`.

> [!IMPORTANT]
> **Delimitação de Escopo desta Nova Fatia:**
> 1. Conexão do executor existente (`catalog_publisher.execute_publication` e `catalog_publisher.resume_publication`) às ações de executar e retomar publicação via **API HTTP** (`POST /api/v1/channel-catalog/publications/{batch_id}/execute` e `.../resume`) e via interface de catálogo do **Channel Hub** (`ChannelHubWorkspace.tsx`).
> 2. Reuso estrito dos modelos canônicos, capacidades e permissões existentes (`channel.catalog.manage` para execução/retomada e `channel.catalog.read` para visualização).
> 3. Isolamento rigoroso por tenant/unidade, concessões duráveis de execução (leases), idempotência estrita e conteúdo congelado (frozen payload).
> 4. Execução de I/O externo estritamente fora de transações abertas de banco de dados.
> 5. A interface e a API refletem estados confirmados, pendências e erros sem afirmar publicação antes da confirmação do conector.
> 6. Travessia autenticada de ponta a ponta validada com gestora autorizada e leitora sem permissão de ação, incluindo negativas diretas na API (403), retomada e preservação da venda local durante indisponibilidade do conector.
> 7. Utilização exclusiva do conector de referência (`CONTRACT_TEST`), fechado em produção.
> 8. Preservação dos três nichos: alimentação (`FOOD_SERVICE`), varejo (`RETAIL`) e revenda de beleza (`BEAUTY_RESELLER`).

---

## 2. Modelagem e Estruturas de Dados

A arquitetura do S13.2 reutiliza as entidades canônicas de `app/models/channel_catalog.py`:

1. **`ChannelCatalogOffer`:**
   - Modela o estado corrente de um produto (`product_id`) para uma conexão de merchant (`merchant_connection_id`).
   - Campos: `price`, `available`, `stock_quantity`, `desired_version` (versão almejada no POS), `published_version` (versão confirmada pelo canal) e `last_publication_status` (`PENDING`, `SUCCEEDED`, `FAILED`).
2. **`ChannelPublicationBatch`:**
   - Representa o lote de publicação idempotente gerado para a conexão.
   - Campos: `id`, `tenant_id`, `store_id`, `merchant_connection_id`, `status` (`PENDING`, `PROCESSING`, `PARTIAL`, `SUCCEEDED`, `FAILED`), `idempotency_key`, `request_hash`, `created_by`.
   - **Campos da Migração 102:**
     - `snapshot_version: int`: versão sequencial do snapshot/lote por conexão, desacoplada da `desired_version` individual das ofertas.
     - `content_hash: str` (SHA-256): hash determinístico do conteúdo congelado de todos os itens do lote, segregado do `request_hash`.
   - **Campos da Migração 103 (`103_the_publication_batch_leases`):**
     - `lease_token: Optional[str]`: token efêmero de concessão do executor ativo.
     - `lease_expires_at: Optional[datetime]`: instante limite de expiração da concessão durável contra despachos simultâneos locais.
3. **`ChannelPublicationItem`:**
   - Modela cada oferta participante do lote e seu resultado específico junto ao canal.
   - Campos: `batch_id`, `offer_id`, `desired_version`, `provider_operation_key`, `status` (`PENDING`, `SUCCEEDED`, `FAILED`), `attempt_count`, `provider_result_ref`, `error_code`, `error_message`.
   - **Campo da Migração 102:**
     - `frozen_payload: dict` (JSON): congela o snapshot exato dos dados e atributos do produto/oferta no momento da geração do lote.

---

## 3. Correções Fundamentais e Grupos de Proteção

### Grupo 1: Proteção da Concessão de Execução (Lease) e Retomada
- **Conferência estrita do `lease_token` sob lock:** Antes de alterar o estado de execução ou liberar a concessão, o executor confere se `batch.lease_token == active_token`. Um executor antigo que sofre atraso não apaga nem substitui a concessão adquirida por outro (reprovando com HTTP `409` e efetuando rollback).
- **Proteção contra segundo envio na retomada:** A retomada `resume_publication` adquire concessão durável sob bloqueio antes de qualquer ação externa e verifica se outro executor mantém concessão ativa; caso positivo, rejeita a chamada com `409`. Aplicar um resultado consultado não abre brecha nem habilita reenvios indevidos.
- **Consulta prévia na retomada pós-expiração:** Retomada após expiração de lease consulta a operação no conector via `check_catalog_status` antes de decidir pelo reenvio. Se todos os itens já constarem como confirmados, o lote é concluído como `SUCCEEDED` sem efetuar nova chamada de despacho (`publish_catalog`).
- **Contagem rigorosa de despachos:** A exclusividade de execução é comprovada pela contagem exata de chamadas e registros no conector, e não apenas por "ao menos um sucesso".
- **Aviso sobre Desduplicação Externa:** A concessão local reduz corridas locais no POS, mas **não impede um processo antigo de agir no provedor**; a deduplicação externa por chave de operação estável e conteúdo congelado permanece mandatória.

### Grupo 2: Monotonicidade Completa e Atualização do Identity Map
- **Atualização do Identity Map (`populate_existing=True`):** Ao adquirir bloqueios ordenados (`ORDER BY id FOR UPDATE`) sobre as ofertas, a query executa com `.execution_options(populate_existing=True)`. Isso garante que instâncias já presentes no cache da `Session` reflitam os valores persistidos no banco de dados por sessões concorrentes mais recentes.
- **Proteção de `ChannelPublicationItem` e `ChannelPublicationBatch`:** Uma vez confirmado com sucesso (`SUCCEEDED`), uma resposta tardia de falha (inclusive via rota legada `channel_catalog_service.apply_results`) **não rebaixa o item nem o lote para `FAILED` ou `PARTIAL`**, nem reabre o lote para republicação. A evidência do sucesso é preservada e um diagnóstico explícito de advertência é emitido em log.
- **Regra Central Unificada:** A mesma regra central de monotonicidade e ordenação é utilizada nos três caminhos: `execute_publication`, `resume_publication` e `apply_results`.

### Grupo 3: Conector de Referência Recuperável e Idempotente
- **Registro Local Durável em SQLite:** O conector de referência utiliza armazenamento SQLite local isolado de testes (`reference_catalog_dispatches` e `reference_simulated_failures`), sobrevivendo ao término ou reinício completo de processos.
- **Recuperação por Conteúdo Idêntico:** Reenvio de operação já confirmada com o mesmo hash completo de conteúdo recupera o resultado original persistido, sem executar novamente a operação nem sobrescrever sucesso por falhas configuradas a posteriori.
- **Recusa de Conteúdo Divergente:** Envio com a mesma chave de operação e conteúdo divergente é recusado com código `DIVERGENT_CONTENT`.
- **Prova Multi-Processo:** Comprovada a troca de mensagens entre processos Python independentes (via `subprocess`), confirmando que um novo processo recupera a confirmação no conector durável sem rede e sem reexecutar.

### Grupo 4: Monotonicidade Residual no Caminho Legado (`apply_results`) — Aprovado em `f094468`
- **Recarga de `ChannelPublicationBatch`:** Preserva filtros de tenant/unidade e bloqueio `FOR UPDATE`, com `.execution_options(populate_existing=True)`.
- **Recarga de `ChannelPublicationItem`:** Carrega itens ordenados por `id`, sob `.with_for_update()` e `.execution_options(populate_existing=True)`, atualizando o identity map antes da aplicação das regras centrais de monotonicidade.
- **Prova de Intercalamento com Três Sessões:** Session A retém referências fortes a lote e itens pendentes; Session B confirma publicação e faz commit; sem expirar a Session A, ela recebe falha tardia via `apply_results`. A Session C comprova que lote e itens permanecem `SUCCEEDED` (no lote completo) ou `PARTIAL`/`SUCCEEDED` (no parcial), com contagem de chamadas a `publish_catalog` rigorosamente inalterada.
- **Controle Negativo:** Removida a recarga com `populate_existing=True`, o teste reprova com diagnóstico `FAILED/FAILED/SUCCEEDED`.

### Grupo 5: Conexão do Executor à API e Channel Hub UI (Nova Fatia Delimitada)
- **Endpoints de Execução e Retomada:**
  - `POST /api/v1/channel-catalog/publications/{batch_id}/execute`: aciona `service.execute_batch`, obtém concessão durável, executa chamada fora de transação do banco, aplica monotonicamente resultados e emite trilha de auditoria/outbox. Requer permissão canônica `channel.catalog.manage`.
  - `POST /api/v1/channel-catalog/publications/{batch_id}/resume`: aciona `service.resume_batch`, consulta status prévio no conector e retoma apenas itens pendentes/falhos preservando concessão. Requer `channel.catalog.manage`.
- **Integração no Frontend (`ChannelHubWorkspace.tsx` e `api.ts`):**
  - Publicação no diálogo de catálogo gera o lote e aciona imediatamente `executeChannelPublicationBatch`.
  - Feedback visual transparente baseado no status real reportado pelo servidor: toasts informam conclusão com sucesso, falha total ou falha parcial com itens retidos.
  - Cartões de lotes exibem badges de status (`SUCCEEDED`, `PARTIAL`, `FAILED`, `PENDING`) e os botões "Executar" (para lotes pendentes) e "Retomar" (para lotes com falhas parciais ou erros), condicionados à autoridade de gestão (`canManage`).
  - Nenhuma asserção de publicação é feita antes da confirmação inequívoca do canal.
- **Travessia Autenticada de Homologação (`test_channel_catalog_execution_walkthrough.py`):**
  - **Leitora sem permissão de ação (`channel.catalog.manage` = DENY):** consulta livremente o catálogo (`GET /catalog` $\rightarrow$ 200), mas tem mutações na API estritamente recusadas com HTTP `403 Forbidden` (`/mappings`, `/offers`, `/publications`, `/execute`, `/resume`), com mensagens amigáveis em português e sem vazamento de chaves técnicas.
  - **Gestora autorizada (`channel.catalog.manage` = ALLOW):** executa publicações, atinge confirmações `SUCCEEDED`, inspeciona falhas parciais e comanda retomadas com sucesso.
  - **Preservação da Venda Local no PDV:** durante indisponibilidade total simulada do conector externo (HTTP 503 / timeout na publicação de catálogo), o fluxo completo de checkout no PDV (`/sales`, `/items`, `/checkout`) executa instantaneamente sem lockouts, sem atrasos e sem conexões retidas no banco de dados.
  - **Três Nichos Reais:** produtos de Alimentação, Varejo e Revenda de Beleza são operados de forma agnóstica, comprovando ausência de dependências indevidas de cozinha ou mesas para varejo e beleza.

### Grupo 6: Resolução dos Bloqueios da Revisão de 02/10/2026 (P1 a P4)

1. **[P1] Auditoria e Outbox Transacionais no Desfecho da Recuperação Parcial (`catalog_publisher.py`):**
   - Em `resume_publication`, o registro dos eventos de outbox e auditoria (`channel.catalog.resumed` e `channel.publication.resumed`) foi unificado e estendido para cobrir todos os desfechos:
     - Saída rápida sem itens pendentes registra desfecho antes do commit.
     - Recuperação total (`conclusive_count == total_items`) registra desfecho com status `SUCCEEDED`.
     - **Recuperação parcial:** na Etapa 3, quando a consulta ao conector resolve parte dos itens, os resultados conclusivos e a atualização de versão das ofertas são persistidos monotonicamente juntamente com os eventos de desfecho da recuperação (`conclusive_count`, `remaining_pending_count`, status `PARTIAL`) *na mesma transação atômica* antes do commit pré-reenvio. Se a intenção do reenvio subsequente falhar, a base preserva atomicamente o estado parcial com sua respectiva trilha de auditoria/outbox registrada.
2. **[P2] Distinção Visual de Itens e Controles de Ação no Channel Hub (`ChannelHubWorkspace.tsx` e `channelCatalogPresentation.ts`):**
   - **Rotulagem Contextual Precisa por Tentativa Individual:** O estado `PARTIAL` ou `FAILED` do lote não é prova de tentativa individual. Para itens `PENDING` fora de lote `PROCESSING`, a rotulagem é decidida estritamente pelo contador individual `attempt_count`: zero tentativas (`attempt_count = 0`) exibe **"Pendente de envio"** (mesmo em lotes parciais/falhos), enquanto contador positivo (`attempt_count > 0`) sem confirmação definitiva exibe **"Tentativa sem confirmação"** com destaque de alerta (`text-state-warning font-bold`). A ordem rigorosa de precedência de apresentação é:
     1. Confirmação definitiva (`SUCCEEDED`) $\rightarrow$ "Confirmado"
     2. Falha de rede / timeout (`FAILED` com código de erro de transporte) $\rightarrow$ "Resposta não confirmada"
     3. Rejeição de negócio (`FAILED` com `BUSINESS_REJECTION` ou erro do canal) $\rightarrow$ "Rejeitado pelo canal"
     4. Execução em andamento no lote (`PROCESSING`) $\rightarrow$ "Em execução"
     5. Tentativa registrada sem confirmação (`PENDING` com `attempt_count > 0`) $\rightarrow$ "Tentativa sem confirmação"
     6. Pendente sem despacho (`PENDING` com `attempt_count = 0`) $\rightarrow$ "Pendente de envio"
   - **Controles de Ação Visíveis e Explicativos:** para operadoras com perfil gestor (`canManage`), os botões de ação ("Publicar", "Executar", "Retomar") permanecem visíveis mesmo quando a conexão está inativa (`SUSPENDED`) ou sem capacidade (`CATALOG_PUBLICATION`), sendo renderizados desabilitados (`disabled={true}`) e munidos de tooltip explicativo (`title="Conexão não está ativa ou conector não suporta publicação de catálogo neste ambiente"`), garantindo clareza e previsibilidade de interface.
   - **Liberação de Busy e Releitura via Finally:** as ações de Publicar, Executar e Retomar mantêm `busy = true` durante toda a mutação e releitura do catálogo (`refreshBacklog`), liberando o controle de forma determinística no bloco `finally`, prevenindo reenvios concorrentes ou travamentos em tela mesmo em caso de erro na releitura.
3. **[P3] Prova Transacional com Falha Injetada na Auditoria/Outbox (`test_channel_catalog_execution_walkthrough.py`):**
   - O Cenário C foi refatorado para injetar falha transacional real em `write_audit_and_outbox` durante a Fase 3 de `execute_publication` (`channel.catalog.executed`). Comprova rollback integral na Fase 3: o rollback desfaz a tentativa de liberação do lease e preserva o lease concedido e persistido na Fase 1 ativo no banco de dados; lote permanece `PROCESSING`, item permanece `PENDING` com tentativa registrada (`attempt_count = 1`), versão da oferta permanece 0, e 0 eventos de desfecho são gravados. A retomada subsequente consulta o conector e conclui com sucesso com contagem exata de 1 despacho inicial e 0 chamadas adicionais a `publish_catalog`.
   - O Cenário D valida a mesma resiliência atômica com falha injetada no evento de desfecho da retomada (`channel.catalog.resumed`), preservando `PROCESSING`, lease ativo, item em `PENDING` com `attempt_count = 1` e 0 eventos de desfecho.
   - O Cenário E reproduz com fidelidade o Achado 1: recuperação parcial (1 item confirmado, 1 não resolvido) onde a gravação da intenção de reenvio falha. Comprova que o item confirmado retém `SUCCEEDED` com avanço estrito de versão de 0 para 1 e que os eventos de desfecho da recuperação parcial (`channel.publication.resumed` e `channel.catalog.resumed`) estão devidamente gravados no banco com payloads JSON validados (`conclusive_count = 1`, `remaining_pending_count = 1`, `status = "PARTIAL"`).
4. **[P4] Cobertura da Travessia em Navegador e Separação Rigorosa de Contratos (`hom10_publicacao_catalogo.cjs`):**
   - Travessia em Chromium real executando ações reais da interface contra contratos mockados:
     1. Lote próprio `PENDING` carregado inicialmente com botão "Executar" habilitado e item com zero tentativas exibindo "Pendente de envio".
     2. Distinção individual de itens em lote `PARTIAL`: item confirmado ("Confirmado"), item com tentativa ("Tentativa sem confirmação") e item sem tentativa ("Pendente de envio").
     3. Gestora aciona "Publicar (2)" sob falha HTTP 504 de transporte/timeout na chamada de execução do canal: toast de erro exibido, releitura via `finally`, contadores de mutação separados (1 criação, 1 execução), lote renderizado em `PARTIAL`.
     4. Ação "Executar" acionada contra contrato HTTP 200/PARTIAL (exceção externa capturada pelo executor): `waitForResponse` do POST, controle determinístico de busy durante releitura retida, toast "Lote executado com pendências parciais.", badge atualizado para `Parcial` com botão "Retomar" habilitado, e linha do item exibindo exclusivamente "Tentativa sem confirmação" (sem Confirmado, Rejeitado ou Pendente de envio).
     5. Renderização dedicada de rejeição conclusiva de negócio: lote com item `FAILED`/`BUSINESS_REJECTION` exibindo "Rejeitado pelo canal · BUSINESS_REJECTION" e item `SUCCEEDED` exibindo "Confirmado".
     6. Executar lote `PENDING` com erro 500 após persistência de `PROCESSING`: releitura via `finally` atualiza tela para `PROCESSING` sem reenvio automático.
     7. Retomar lote `PARTIAL` com erro 500: releitura atualiza badge para `PROCESSING` e item para "Em execução".
     8. Retomar com recuperação parcial já persistida: erro no reenvio, releitura devolve item 1 "Confirmado" e item 2 "Pendente de envio", com contadores conferidos.
     9. Falha na releitura do catálogo: erro tratado com toast, contadores conferidos e `busy` liberado sem deadlock.
     10. Conexão inativa (`SUSPENDED`) e sem capacidade (`CATALOG_PUBLICATION`): botões desabilitados com tooltip explicativo e 0 mutações.
     11. Retomada sob lease ativo gerando 409 informativo vs autorizada após expiração.
     12. Sessão Leitora: acesso livre de consulta e ausência total de botões de mutação e checkboxes.
   - Declaração explícita de camadas: o roteiro Chromium utiliza contratos OpenAPI mockados no navegador, enquanto o teste integrado ponta a ponta com banco real PostgreSQL e conector durável SQLite é `test_channel_catalog_execution_walkthrough.py`.

---

## 4. Matriz de Provas Automatizadas

### A. Testes Fundacionais do Executor (`test_channel_catalog_publication.py`) — 32 Testes Aprovados

| Teste | Requisito / Critério Comprovado | Tipo de Prova | Resultado |
|---|---|---|---|
| `test_lote_nunca_enviado_nao_ganha_published_version_pela_consulta` | Conector responde UNKNOWN para chave não enviada; consulta não avança versão. | Isolamento | `PASSED` |
| `test_confirmacao_perdida_recupera_resultado_efetivamente_registrado` | Queda de rede recupera resultado registrado no conector sem reenvio cego. | Isolamento | `PASSED` |
| `test_rejeicao_nao_vira_sucesso_sem_padrao_textual_fail` | Rejeição sem string "FAIL" é registrada e recuperada como FAILED. | Isolamento | `PASSED` |
| `test_duas_sessoes_confirmacao_antiga_nao_sobrescreve_versao_mais_nova_na_retomada` | Confirmação atrasada da v1 em sessão concorrente não sobrescreve v2 já gravada. | Concorrência (2 sessões) | `PASSED` |
| `test_resposta_fora_de_ordem_confirmacao_antiga_nao_regride_versao_nova` | Resposta tardia de versão anterior mantém a versão mais recente da oferta. | Monotonicidade | `PASSED` |
| `test_resposta_fora_de_ordem_falha_antiga_nao_sobrescreve_sucesso_posterior` | Falha tardia de versão anterior não anula o status SUCCEEDED da versão atual. | Monotonicidade | `PASSED` |
| `test_lote_legado_sem_snapshot_permanece_nao_publicavel_com_422` | Lote legado sem snapshot congelado é rejeitado com 422 e diagnóstico claro. | Validação estrita | `PASSED` |
| `test_payload_incompleto_rejeitado_com_422_sem_defaults_distorcidos` | Snapshot sem preço, produto ou disponibilidade não usa defaults e gera 422. | Validação estrita | `PASSED` |
| `test_recuperacao_lote_legado_pelo_algoritmo_anterior_de_request_hash` | Algoritmo legado de request_hash recupera lote original com mesma chave. | Retrocompatibilidade | `PASSED` |
| `test_preservacao_provider_operation_key_legada` | Prefixo legado `catalog:...` armazenado no banco é preservado no despacho. | Retrocompatibilidade | `PASSED` |
| `test_alteracoes_de_produto_e_oferta_avancam_versao_e_chave` | Mudança de título, SKU, preço e disponibilidade avançam versão e chave. | Versionamento atômico | `PASSED` |
| `test_mesma_chave_com_conteudo_divergente_rejeitada_com_409` | Tentativa de associar mesma chave com conteúdo divergente gera 409. | Idempotência estrita | `PASSED` |
| `test_reenvio_preserva_identidade_e_conteudo_originais` | Retentativas mantêm a mesma chave de operação e o mesmo payload congelado. | Idempotência estrita | `PASSED` |
| `test_criacoes_concorrentes_com_chaves_distintas_avancam_versoes_sem_colisao` | Duas criações simultâneas na conexão avançam snapshot_version sem colisão. | Concorrência (threads) | `PASSED` |
| `test_criacoes_concorrentes_com_mesma_chave_recuperam_mesmo_lote` | Duas criações simultâneas com mesma chave recuperam lote sem IntegrityError. | Concorrência (threads) | `PASSED` |
| `test_dois_executores_concorrentes_apenas_um_despacha_por_lease` | Concorrência de executores barra o segundo via lease durável com 409. | Concorrência (threads) | `PASSED` |
| `test_queda_apos_envio_antes_da_confirmacao_retomada_consulta_sem_reenviar` | Crash após envio recupera confirmação no conector sem reenvio duplicado. | Resiliência / Queda | `PASSED` |
| `test_zero_conexoes_banco_retidas_durante_chamada_ao_conector` | Medição direta no pool: zero conexões retidas durante chamada ao adaptador. | Medição de Recursos | `PASSED` |
| `test_publicacao_idempotente_com_mesma_chave_recupera_lote_original_apos_mudancas_no_catalogo` | Rechamada idempotente recupera lote original após alterações no catálogo. | Idempotência | `PASSED` |
| `test_publicacao_executa_fora_de_transacao_de_banco_e_atualiza_monotonico` | Transações curtas locais com I/O fora de locks e monotonicidade de versão. | Transacionalidade | `PASSED` |
| `test_resultados_parciais_e_retomada_com_chave_estavel` | Falha pontual em item do lote permite retomada preservando chave estável. | Retomada | `PASSED` |
| `test_tres_nichos_e_combinado_sem_imposicao_de_cozinha_ou_mesas` | Nichos reais (alimentação, varejo, revenda de beleza) e combinado sem imposição de cozinha. | Domínio de Negócio | `PASSED` |
| `test_lease_a_perde_b_assume_a_atrasado_nao_apaga_b_nem_habilita_c` | A perde concessão; B assume; A atrasado não apaga B nem habilita C; contagem exata. | Concorrência (Grupo 1) | `PASSED` |
| `test_retomada_durante_execucao_ativa_nao_provoca_segundo_envio` | Retomada durante execução ativa rejeitada com 409 sem segundo envio ao conector. | Concorrência (Grupo 1) | `PASSED` |
| `test_retomada_apos_expiracao_consulta_antes_de_decidir_reenvio` | Retomada pós-expiração consulta o conector antes de reenvio; despacho único (count=1). | Concorrência (Grupo 1) | `PASSED` |
| `test_session_stale_identity_map_populate_existing_mantem_versao_mais_nova` | Session com cache stale recarrega v2 com populate_existing e não regride para v1 antiga. | Concorrência (Grupo 2) | `PASSED` |
| `test_falha_tardia_via_apply_results_mantem_item_lote_e_oferta_coerentes` | Falha tardia via apply_results não rebaixa item, lote nem oferta confirmados com sucesso. | Monotonicidade (Grupo 2) | `PASSED` |
| `test_conector_referencia_registro_sqlite_duravel_entre_processos` | Persistência SQLite durável comprovada entre processos Python independentes via subprocess. | Multi-Processo (Grupo 3)| `PASSED` |
| `test_conector_referencia_reenvio_mesmo_conteudo_recupera_e_recusa_divergente` | Reenvio de mesmo conteúdo recupera sucesso original; conteúdo divergente gera DIVERGENT_CONTENT. | Idempotência (Grupo 3) | `PASSED` |
| `test_apply_results_lote_completo_intercalamento_sessoes_mantem_succeeded` | Intercalamento de sessões no lote completo: recarga sob bloqueio com populate_existing mantém SUCCEEDED; zero despachos extras. | Monotonicidade (Grupo 4) | `PASSED` |
| `test_apply_results_lote_parcial_intercalamento_sessoes_mantem_partial` | Intercalamento no lote parcial: item confirmado SUCCEEDED, item pendente PENDING, lote PARTIAL; zero despachos extras. | Monotonicidade (Grupo 4) | `PASSED` |
| `test_controle_negativo_sem_recarga_dos_itens_reprova_com_failed_failed_succeeded` | Controle negativo: sem recarga com populate_existing, falha tardia reproduz FAILED/FAILED/SUCCEEDED e reprova asserção. | Controle Negativo (Grupo 4) | `PASSED` |

### B. Travessia Autenticada e Resiliência Local (`test_channel_catalog_execution_walkthrough.py`) — 10 Testes Aprovados (Total de 50 testes na suíte selecionada)

| Teste | Requisito / Critério Comprovado | Tipo de Prova | Resultado |
|---|---|---|---|
| `test_leitora_tem_leitura_livre_mas_mutacoes_sao_recusadas_com_403` | Leitora consulta `GET /catalog` com 200, mas qualquer mutação (`/mappings`, `/offers`, `/publications`, `/execute`, `/resume`) é rejeitada com 403 amigável sem vazar chaves de permissão. | Autorização / Negativas Diretas na API | `PASSED` |
| `test_gestora_executa_publicacao_completa_e_confirma_estado_succeeded` | Gestora autenticada cria lote nos 3 nichos, executa via `POST /execute` e atinge status confirmado `SUCCEEDED` sem antecipação indevida na vitrine. | Travessia Autenticada Gestora | `PASSED` |
| `test_falha_parcial_exibe_erros_leitora_e_gestora_retoma_com_sucesso` | Lote com falha pontual em item atinge `PARTIAL`, expõe diagnóstico detalhado na vitrine, barra retomada por leitora e permite retomada com sucesso e monotonicidade pela gestora. | Falha Parcial e Retomada na API | `PASSED` |
| `test_checkedout_zero_na_entrada_do_conector_em_execute_e_resume` | Chamadas HTTP autenticadas de `execute` e `resume` encerram a sessão da requisição logo após resolver o contexto (padrão R14), medindo `checkedout == 0` na entrada isolada de `publish_catalog` e `check_catalog_status`. | Liberação de Sessão / Pool (Bloco 1) | `PASSED` |
| `test_negativas_conexao_inativa_ou_sem_capacidade_preservam_estado_e_sem_chamada_externa` | Conexão `SUSPENDED` ou adaptador sem `CATALOG_PUBLICATION` gera recusa HTTP 400 controlada, sem despachos externos (count=0), sem incremento de tentativas e sem concessão/PROCESSING pendente; verificado em `execute` e `resume`. | Validação Pré-Despacho (Bloco 2) | `PASSED` |
| `test_auditoria_e_outbox_transacionais_com_alteracoes_locais` | Intenção na Fase 1 (`action="channel.catalog.execute"`, `event_type="channel.publication.intent_dispatched"`), desfecho na Fase 3 (`action="channel.catalog.executed"`, `event_type="channel.publication.executed"`). Cobre Cenário A (sucesso total), Cenário B (aborto pré-despacho), Cenário C (falha na auditoria do desfecho: o rollback desfaz a liberação do lease e preserva o lease concedido na Fase 1 ativo no banco; contagem exata de 1 despacho inicial e 0 adicionais na retomada), Cenário D (falha no desfecho de retomada: rollback atômico preserva status `PROCESSING`, lease ativo, item `PENDING` com `attempt_count=1`, `published_version=0` e 0 eventos de desfecho) e Cenário E (recuperação parcial com produtos dedicados avança estritamente de 0 para 1, persiste item e grava eventos com validação dos payloads JSON: `conclusive_count=1`, `remaining_pending_count=1`, `status="PARTIAL"`). | Auditoria e Outbox Transacionais (Bloco 3 / P1 e P3) | `PASSED` |
| `test_retomada_de_processing_com_lease_ativo_retorna_409_e_expirado_prossegue` | Retomada de lote em `PROCESSING` com lease ativo recusa com HTTP 409 e mensagem clara; com lease expirado assume nova concessão e conclui com `SUCCEEDED`. | Concorrência e Lease na Retomada (Bloco 4) | `PASSED` |
| `test_venda_local_funciona_normalmente_durante_bloqueio_do_conector_externo` | Concorrência real sob bloqueio do conector externo via `threading.Event`, com `checkedout == 0` medido na entrada; durante o bloqueio, PDV conclui venda completa de balcão (5 etapas: criação, itens multi-nicho, checkout, pagamento em dinheiro, confirmação atômica `PAID`) com latência aferida sob estrito limite temporal (< 2,0s), liberando o conector em seguida. | Concorrência Real e Desacoplamento do PDV (Bloco 4) | `PASSED` |
| `test_tres_nichos_sem_imposicao_de_cozinha_ou_mesas` | Produtos de Varejo e Revenda de Beleza operam sem dependência de pontos de produção/cozinha ou mesas, com publicação limpa em lote dedicado. | Agnosticismo de Nicho | `PASSED` |
| `test_retomada_sem_itens_pendentes_finaliza_com_desfecho_atomico_e_reverte_na_falha` | Saída rápida de retomada quando todos os itens já foram concluídos: finaliza lote como `SUCCEEDED` e grava desfecho atomicamente na Fase 1 com zero chamadas externas ao conector; falha na escrita do desfecho reverte a transação de forma atômica (rollback comprovado). | Atomicidade no Ramo Sem Pendências | `PASSED` |

### C. Contratos de API e Superfície de Rotas (`test_frontend_api_contract.py` e `test_surface_reachability.py`)

- **Contratos Frontend/Backend:** 100% de paridade para `/publications/{batch_id}/execute` e `/publications/{batch_id}/resume`.
- **Rotas Alcançáveis:** 0 rotas órfãs, 0 endpoints inacessíveis.
- **Total do Backend Selecionado:** 50 testes aprovados (32 em `test_channel_catalog_publication.py`, 10 em `test_channel_catalog_execution_walkthrough.py`, 3 em `test_frontend_api_contract.py`, 5 em `test_surface_reachability.py`). O aumento de 49 para 50 decorre da inclusão da prova dedicada para o ramo sem itens pendentes.

### D. Interface do Frontend (`s13-channel-catalog.test.ts` e Suíte Global)

- **206 testes automatizados no frontend:** 100% aprovados (`npm test`).
  - `getItemPresentationStatus` (módulo puro `domain/channelCatalogPresentation.ts`) testado exaustivamente em `s13-channel-catalog.test.ts`, distinguindo com precisão itens `PENDING` fora de `PROCESSING`: `attempt_count = 0` exibe "Pendente de envio"; `attempt_count > 0` exibe "Tentativa sem confirmação" (Defeito 1 corrigido).
  - Recarga do backlog após mutações (`refreshBacklog` em `finally`) implementada em Publicar, Executar e Retomar: atualização ocorre tanto no sucesso quanto no erro, mantendo `busy = true` durante a leitura e liberando o bloqueio de forma segura mesmo se a leitura falhar, sem reenvio automático (Defeito 2 corrigido).
- **Build de produção:** `tsc && vite build` concluído com sucesso e 0 erros de tipagem (`built in 10.24s`).

### E. Travessia Automatizada em Navegador Real (`frontend/e2e/presentation/hom10_publicacao_catalogo.cjs`)

- **Navegador Real:** Executado via Playwright com Chromium real headless na porta isolada `5195`.
- **Camada de Apresentação:** Valida interações reais do operador, rendering de estados, tooltips contextuais, toasts de erro e RBAC (com contratos de API simulados no navegador; o teste integrado com banco PostgreSQL real é `test_channel_catalog_execution_walkthrough.py`).
- **Casos Obrigatórios Validados:**
  1. No mesmo lote `PARTIAL`, item `PENDING` com `attempt_count = 0` exibe "Pendente de envio", item `PENDING` com `attempt_count = 1` exibe "Tentativa sem confirmação" e item `SUCCEEDED` exibe "Confirmado" (aferido por linha de produto).
  2. Executar lote `PENDING`: resposta 500 do servidor após o backend transicionar para `PROCESSING` com lease ativo; a releitura via `finally` atualiza a tela removendo o botão "Executar" e exibindo `PROCESSING`, com exatamente 1 chamada POST (sem reenvio automático).
  3. Retomar lote `PARTIAL`: resposta de erro 500; releitura pós-erro atualiza badge do lote para `PROCESSING` e item para "Em execução".
  4. Retomar com recuperação parcial já persistida: falha simulada na intenção de reenvio pós-recuperação; releitura mostra item 1 como "Confirmado" e item 2 como "Pendente de envio" (`attempt_count = 0`), sem duplicação de lote e com contadores conferidos.
  5. Falha na releitura de atualização: erro de leitura tratado com toast informativo e liberação de `busy` sem deadlock ou bloqueio permanente, com contadores conferidos.
  6. Separação rigorosa de contratos de execução e falha:
     - **Contrato A (exceção externa capturada pelo executor):** ação Executar no navegador retorna HTTP 200 com lote `PARTIAL` e item em `PENDING` com `attempt_count = 1` (sem confirmação nem rejeição fabricada), exibindo toast informativo "Lote executado com pendências parciais.", controle determinístico de busy durante a releitura retida via `finally`, transição de badge para `Parcial` com botão "Retomar" habilitado, e item exibindo "Tentativa sem confirmação" (sem Confirmado, Rejeitado pelo canal ou Pendente de envio).
     - **Contrato B (falha de rede / timeout HTTP 504 na chamada de execução do canal):** exibe toast de erro de transporte claro para a operadora, aciona releitura do backlog via `finally`, com contadores separados de criação (1 POST `/publications`) e execução (1 POST `/execute`), refletindo o lote em `PARTIAL` com item com tentativa em "Tentativa sem confirmação".
     - **Renderização de rejeição conclusiva de negócio (`BUSINESS_REJECTION`):** fixture dedicada comprovando que item `FAILED` com código de erro de negócio exibe "Rejeitado pelo canal · BUSINESS_REJECTION" e item `SUCCEEDED` exibe "Confirmado".
  7. Conexão inativa (`SUSPENDED`) e conexão sem capacidade (`CATALOG_PUBLICATION`): presença confirmada para a gestora de Publicar, Executar e Retomar, todos com atributo `disabled`, tooltip explicativo correspondente e zero mutações disparadas ao clique.
  8. Sessão de Leitora: acesso irrestrito de consulta ao catálogo e lotes, ausência de botões de mutação e de checkboxes de seleção. Retomada sob lease ativo gerando 409 tratado em toast e retomada pós-expiração autorizada com sucesso.
- **Evidências Geradas:** Relatório `artifacts/hom-publicacao/walkthrough_report.json` e 13 capturas de tela:
  - `01b_lote_parcial_distincao_tentativas_pendente_vs_incerto.png`
  - `01_gestora_publicar_timeout_tentativa_sem_confirmacao.png`
  - `06b_contrato_200_partial_capturado.png`
  - `06c_renderizacao_rejeicao_negocio_business_rejection.png`
  - `02b_executar_erro_recarrega_processing.png`
  - `03b_retomar_erro_recarrega_processing.png`
  - `04b_retomada_parcial_persistida_confirmado_e_pendente.png`
  - `05b_falha_releitura_libera_busy.png`
  - `03_retomada_concorrente_409_lease_ativo.png`
  - `04_retomada_lease_expirado_sucesso.png`
  - `05_conexao_suspended_acoes_desabilitadas.png`
  - `06_conexao_sem_capacidade_acoes_desabilitadas.png`
  - `07_leitora_somente_leitura.png`

---

## 5. Salvaguardas e Compromissos Mantidos

1. **Gate S10.1 Mantido Fechado:** Nenhuma alteração nos requisitos aprovados de S10.1 (D1/R11 preservada, migração 101 intocada).
2. **Migrações Publicadas Intocadas:** A migração publicada `102_the_catalog_snapshot_freezes` e a migração `103_the_publication_batch_leases` permanecem estritamente preservadas e sem alterações. Zero drift no `alembic check`.
3. **Decisões D2 e D8 Não Aprovadas:** Permanecem fora do código funcional.
4. **Permissões D7:** Permanecem não concedidas a nenhum perfil padrão ou rota de acesso.
5. **Purga Física (P12–P16):** Mantida formalmente pendente para etapa posterior de retenção.
6. **Infraestrutura e Custos:** Nenhuma contratação de infraestrutura paga ou canais comerciais ativados.
7. **Entrega Delimitada para Revisão:** Código, testes e documentação entregues antes de qualquer commit ou push para revisão pelo usuário.
