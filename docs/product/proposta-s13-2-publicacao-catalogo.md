# Proposta — S13.2: Publicação Fundacional de Catálogo no Channel Hub

Data: 01 de outubro de 2026<br>
Status: **S10.1 FECHADO E CONSOLIDADO; S13.2 PRIMEIRA FATIA FUNDACIONAL CONCLUÍDA E PROVADA (GRUPOS 1, 2 E 3)**<br>
Base: `6d6d85d` em `main` (Gate interno fundacional do S10.1 concluído, CI 36931765783 verde nos 4 jobs).<br>
Migrações: `102_the_catalog_snapshot_freezes` (publicada) $\rightarrow$ `103_the_publication_batch_leases` (publicada e validada, sem necessidade de nova migração).

---

## 1. Contexto, Escopo e Estado do Gate

O épico **S10.1** está **formalmente fechado e consolidado**:
- Provas R1 a R20 verdes no CI.
- **R19** comprovado com controle verdadeiro de idempotência por linha (mutante quebrado cria duplicação ativa preservando o original e reprova no detector comum; substituição legítima com dois ativos e um cancelado passa). O controle de commit prematuro permanece preservado como prova separada de atomicidade.
- **P8** comprovado com comparação estrita de snapshots antes e depois da ingestão em cenários com registros pré-existentes de CRM (`customers`), fidelidade/crédito e documentos fiscais, atestando ausência de efeitos colaterais.
- **R20** consolidado com a saída do roteiro final executado com autenticação real (`order_id: d7210e9a-5d54-4552-952b-be771d928fdc`), com separação formal entre a travessia visual da interface (Chopp R$ 18,50) e os cenários backend (−R$ 2,00 e −R$ 3,50 com complementos).

O épico **S13.2 (Catálogo e Integrações Avançadas)** estabelece a via reversa: a publicação controlada, versionada e idempotente do catálogo do DASHEM POS para canais de venda externos (marketplaces e e-commerce).

> [!IMPORTANT]
> **Delimitação de Escopo desta Fatia:**
> 1. O executor fundacional de publicação de catálogo (`catalog_publisher`) **ainda NÃO está conectado a rotas HTTP públicas (ex.: endpoints de executar/retomar em `/api/v1/channels/catalog/...`) nem a workers de produção em segundo plano (Celery, cron ou filas)**. Sua execução e retomada ocorrem exclusivamente via chamadas internas de serviço testadas diretamente no conector de referência.
> 2. O conector simulado é exclusivamente o `ReferenceChannelAdapter` (`CONTRACT_TEST`), respaldado por armazenamento SQLite local isolado de testes. Nenhum canal comercial foi contratado ou ativado.

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

### Critério Adicional: Medições e Delimitações de Governança
- **Zero Conexões Retidas Durante I/O:** Medição direta no pool do SQLAlchemy durante a chamada de rede externa comprova `engine.pool.checkedout() == 0`.
- **Três Nichos Reais do Sistema:** Validação nos três nichos reais do DASHEM POS: **alimentação** (food service), **varejo** (mercado / comércio geral) e **revenda de beleza** (cosméticos e estética), além de tenant combinado, garantindo que preços derivam exclusivamente dos cadastros/fixtures e que varejo e beleza operam sem imposição de cozinha ou mesas.
- **Delimitação da Análise Estática de Logs:** A garantia de ausência de dados pessoais (P3) restringe-se à análise estática da AST em `test_no_personal_data_in_logs.py`, comprovando que o executor emite apenas identificadores seguros (`tenant_id`, `batch_id`) e contadores.

---

## 4. Matriz de Provas Automatizadas (`test_channel_catalog_publication.py`)

A suíte completa conta com **29 testes automatizados** validados contra PostgreSQL isolado:

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

---

## 5. Salvaguardas e Compromissos Mantidos

1. **Gate S10.1 Mantido Fechado:** Nenhuma alteração nos requisitos aprovados de S10.1 (D1/R11 preservada, migração 101 intocada).
2. **Migrações Publicadas Intocadas:** A migração publicada `102_the_catalog_snapshot_freezes` e a migração `103_the_publication_batch_leases` permanecem estritamente preservadas e sem alterações.
3. **Decisões D2 e D8 Não Aprovadas:** Permanecem fora do código funcional.
4. **Permissões D7:** Permanecem não concedidas a nenhum perfil padrão ou rota de acesso.
5. **Purga Física (P12–P16):** Mantida formalmente pendente para etapa posterior de retenção.
6. **Infraestrutura e Custos:** Nenhuma contratação de infraestrutura paga ou provedores externos foi efetuada.
