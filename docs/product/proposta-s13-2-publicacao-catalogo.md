# Proposta — S13.2: Publicação Fundacional de Catálogo no Channel Hub

Data: 01 de outubro de 2026<br>
Status: **S10.1 FECHADO E CONSOLIDADO; S13.2 INICIADO (PRIMEIRA FATIA FUNDACIONAL COM CORREÇÕES IMPLEMENTADAS E PROVADAS)**<br>
Base: `519f8de` em `main` (Gate interno fundacional do S10.1 concluído, CI 36921846918 verde).<br>
Migrações: `102_the_catalog_snapshot_freezes` (publicada) $\rightarrow$ `103_the_publication_batch_leases` (criada nesta fatia).

---

## 1. Contexto, Escopo e Estado do Gate

O épico **S10.1** está **formalmente fechado e aceito**:
- Provas R1 a R20 verdes no CI.
- **R19** comprovado com controle verdadeiro de idempotência por linha (mutante quebrado cria duplicação ativa preservando o original e reprova no detector comum; substituição legítima passa). O controle de commit prematuro permanece preservado como prova separada de atomicidade.
- **P8** comprovado com comparação estrita de snapshots antes e depois da ingestão em cenários com registros pré-existentes de CRM (`customers`), fidelidade/crédito e documentos fiscais, atestando ausência de efeitos colaterais.
- **R20** consolidado com a saída do roteiro final executado com autenticação real (`order_id: d7210e9a-5d54-4552-952b-be771d928fdc`), com separação formal entre a travessia visual da interface e os cálculos complexos do backend.

O épico **S13.2 (Catálogo e Integrações Avançadas)** estabelece a via reversa: a publicação controlada, versionada e idempotente do catálogo do DASHEM POS para canais de venda externos (marketplaces e e-commerce).

> [!IMPORTANT]
> **Delimitação de Escopo desta Fatia:**
> 1. O executor fundacional de publicação de catálogo (`catalog_publisher`) **ainda NÃO está conectado a rotas HTTP públicas (ex.: endpoints de executar/retomar em `/api/v1/channels/catalog/...`) nem a workers de produção em segundo plano (Celery, cron ou filas)**. Nesta etapa, sua execução e retomada ocorrem exclusivamente via chamadas internas de serviço testadas diretamente no conector de referência.
> 2. O conector simulado é exclusivamente o `ReferenceChannelAdapter` (`CONTRACT_TEST`). Nenhum canal comercial foi contratado ou ativado.

---

## 2. Modelagem e Estruturas de Dados

A arquitetura do S13.2 reutiliza as entidades canônicas de `app/models/channel_catalog.py`:

1. **`ChannelCatalogOffer`:**
   - Modela o estado corrente de um produto (`product_id`) para uma conexão de merchant (`merchant_connection_id`).
   - Campos: `price`, `available`, `stock_quantity`, `desired_version` (versão almejada no POS), `published_version` (versão confirmada pelo canal) e `last_publication_status` (`PENDING`, `SUCCEEDED`, `FAILED`).
2. **`ChannelPublicationBatch`:**
   - Representa o lote de publicação idempotente gerado para a conexão.
   - Campos: `id`, `tenant_id`, `store_id`, `merchant_connection_id`, `status` (`PENDING`, `PROCESSING`, `PARTIAL`, `SUCCEEDED`, `FAILED`), `idempotency_key`, `request_hash`, `created_by`.
   - **Campos adicionados na Migração 102:**
     - `snapshot_version: int`: versão sequencial do snapshot/lote por conexão, desacoplada da `desired_version` individual das ofertas.
     - `content_hash: str` (SHA-256): hash determinístico do conteúdo congelado de todos os itens do lote, segregado do `request_hash`.
   - **Campos adicionados na Migração 103 (`103_the_publication_batch_leases`):**
     - `lease_token: Optional[str]`: token efêmero de concessão do executor ativo.
     - `lease_expires_at: Optional[datetime]`: instante de expiração da concessão durável contra despachos simultâneos locais.
3. **`ChannelPublicationItem`:**
   - Modela cada oferta participante do lote e seu resultado específico junto ao canal.
   - Campos: `batch_id`, `offer_id`, `desired_version`, `provider_operation_key`, `status` (`PENDING`, `SUCCEEDED`, `FAILED`), `attempt_count`, `provider_result_ref`, `error_code`, `error_message`.
   - **Campo adicionado na Migração 102:**
     - `frozen_payload: dict` (JSON): congela o snapshot exato dos dados e atributos do produto/oferta no momento da geração do lote.

---

## 3. Correções Fundamentais Implementadas

### Critério 1: Consulta do Conector de Referência
- **Registro persistido de envios:** O `ReferenceChannelAdapter` mantém em memória registro thread-safe compartilhado entre instâncias (`_registry`) indexado por `(merchant_external_id, operation_key)`.
- **Ausência de fabricação de sucesso:** A consulta `check_catalog_status` só retorna status baseado nos envios efetivamente recebidos. Chaves nunca recebidas retornam `status="UNKNOWN"` com `error_code="OPERATION_NOT_FOUND"`, **nunca** `SUCCEEDED`.
- **Remoção de padrões textuais:** Nenhuma regra de sucesso ou falha depende de substrings como `"FAIL"` no SKU, título ou chave. Falhas controladas são configuradas via `simulate_failure` ou parâmetros de injeção.
- **Comprovações:**
  - Lote nunca enviado não ganha `published_version` pela simples consulta;
  - Confirmação perdida na rede recupera o resultado efetivamente registrado no conector;
  - Rejeição sem a palavra "FAIL" permanece rejeitada na consulta.

### Critério 2: Aplicação Monotônica sob Concorrência
- **Unificação canônica de regras:** `execute_publication`, `resume_publication` e o caminho legado `channel_catalog_service.apply_results` utilizam a mesma função central `apply_item_results_to_offers`.
- **Bloqueio ordenado sem I/O sob lock:** A leitura e atualização das ofertas utiliza bloqueio ordenado (`ORDER BY id FOR UPDATE`) para prevenir deadlocks. O I/O de rede é executado estritamente antes, fora de qualquer transação de banco.
- **Não regressão e proteção contra fora de ordem:** Confirmação tardia de versão antiga não sobrescreve versão mais recente já confirmada (`desired_version < published_version` é ignorado na oferta); falha tardia de versão anterior não anula sucesso confirmado.
- **Comprovação determinística:** Prova com duas sessões concorrentes onde a confirmação da versão 1 recuperada durante a retomada não regride para 1 a oferta cuja versão 2 já foi confirmada.

### Critério 3: Lotes Legados e Payload Incompleto
- **Remoção de defaults distorcidos:** Eliminados fallbacks silenciosos que convertiam snapshot ausente em preço 0, produto `None` ou disponibilidade `True`.
- **Validação estrita antes do envio:** Função `validate_frozen_payload` rejeita lotes legados sem snapshot (`frozen_payload is None`) e payloads com campos ausentes ou inválidos, retornando `HTTPException(422)` com diagnóstico explícito de que lotes legados não são publicáveis e exigem nova intenção explícita.
- **Reconhecimento do request_hash legado:** A função `_matches_request_hash` aceita tanto o formato canônico atual quanto o gerado pelo `reliability_service.compute_request_hash`, permitindo recuperar lotes legados com a mesma chave e payload, mantendo `409` para divergências reais.
- **Preservação de chaves legadas:** `provider_operation_key` já gravadas no banco (inclusive prefixos legados como `catalog:...`) são preservadas integralmente no envio.

### Critério 4: Uma Chave de Operação, Um Conteúdo
- **Versão apropriada para mudanças de conteúdo:** `prepare_batch` compara o snapshot pretendido com a última publicação do item; se houver alteração em título, SKU, preço, disponibilidade ou estoque, a `desired_version` da oferta avança automaticamente, gerando a versão apropriada.
- **Identidade atrelada ao conteúdo:** A chave operacional incorpora o hash do conteúdo (`pub:{conn_id}:{offer_id}:v{version}:{content_hash[:10]}`).
- **Rejeição de colisão de conteúdo:** Tentativas de reutilizar a mesma chave de operação com conteúdos divergentes são estritamente rejeitadas com HTTP `409`.
- **Reenvios preservados:** Rechamadas idempotentes do mesmo lote recuperam o conteúdo congelado e a chave de operação originais.

### Critério 5: Criação e Execução Concorrentes
- **Atribuição sequencial de snapshot_version:** Serializada por conexão através do bloqueio da linha em `merchant_connections` (`with_for_update()`).
- **Idempotência concorrente sem vazamento de erro:** Concorrência na criação com mesma chave captura `IntegrityError` na chave única e recupera o lote existente sem expor erro interno; payload divergente resulta em `409`.
- **Aquisição durável de execução (durable lease):** Fase 1 de `execute_publication` adquire lease de 60 segundos gravando `lease_token` e `lease_expires_at` com bloqueio de linha. Se outro executor ativo detiver o lease, a execução concorrente é recusada com HTTP `409`.
- **Registro prévio de tentativas:** `attempt_count` é persistido no banco **antes** do início do I/O de rede.
- **Recuperação de crash:** Se o executor cair após despachar para a rede e antes de persistir o resultado, `resume_publication` consulta o adaptador via `check_catalog_status` e conclui a publicação sem reenviar ao canal.
- **Aviso sobre Desduplicação Externa:** O lease durável reduz corridas locais no POS, mas **não substitui a idempotência do provedor externo**, que permanece mandatória pela chave estável de operação e seu conteúdo.

### Critério 6: Medição e Delimitações de Governança
- **Zero conexões retidas durante I/O:** Medição direta no pool do SQLAlchemy durante a invocação de rede comprova que `engine.pool.checkedout() == 0`.
- **Delimitação de P8:** Comprovada a preservação de dados pré-existentes de CRM (`customers`), saldo/crédito e documentos fiscais durante a ingestão de pedidos do canal.
- **Delimitação da Análise Estática de Logs:** A verificação contra vazamento de dados pessoais em logs e prints limita-se à varredura estática AST executada em `test_no_personal_data_in_logs.py`.
- **Cobertura Básica dos Três Nichos:** Validação dos três nichos aprovados (alimentação, varejo e beleza) e combinado, garantindo que preços derivam exclusivamente dos cadastros/fixtures e que varejo e beleza operam sem imposição de cozinha ou mesas.

---

## 4. Matriz de Provas Automatizadas (`test_channel_catalog_publication.py`)

| Teste | Requisito / Critério Comprovado | Resultado |
|---|---|---|
| `test_lote_nunca_enviado_nao_ganha_published_version_pela_consulta` | Conector responde UNKNOWN para chave não enviada; consulta não avança versão. | `PASSED` |
| `test_confirmacao_perdida_recupera_resultado_efetivamente_registrado` | Queda de rede recupera resultado registrado no conector sem reenvio cego. | `PASSED` |
| `test_rejeicao_nao_vira_sucesso_sem_padrao_textual_fail` | Rejeição sem string "FAIL" é registrada e recuperada como FAILED. | `PASSED` |
| `test_duas_sessoes_confirmacao_antiga_nao_sobrescreve_versao_mais_nova_na_retomada` | Sincronização determinística: confirmação atrasada da v1 não sobrescreve v2 já gravada. | `PASSED` |
| `test_resposta_fora_de_ordem_confirmacao_antiga_nao_regride_versao_nova` | Resposta tardia de versão anterior mantém a versão mais recente da oferta. | `PASSED` |
| `test_resposta_fora_de_ordem_falha_antiga_nao_sobrescreve_sucesso_posterior` | Falha tardia de versão anterior não anula o status SUCCEEDED da versão atual. | `PASSED` |
| `test_lote_legado_sem_snapshot_permanece_nao_publicavel_com_422` | Lote legado sem snapshot congelado é rejeitado com 422 e diagnóstico claro. | `PASSED` |
| `test_payload_incompleto_rejeitado_com_422_sem_defaults_distorcidos` | Snapshot sem preço, produto ou disponibilidade não usa defaults e gera 422. | `PASSED` |
| `test_recuperacao_lote_legado_pelo_algoritmo_anterior_de_request_hash` | Algoritmo legado de request_hash recupera lote original com mesma chave. | `PASSED` |
| `test_preservacao_provider_operation_key_legada` | Prefixo legado `catalog:...` armazenado no banco é preservado no despacho. | `PASSED` |
| `test_alteracoes_de_produto_e_oferta_avancam_versao_e_chave` | Mudança de título, SKU, preço e disponibilidade avançam versão e chave. | `PASSED` |
| `test_mesma_chave_com_conteudo_divergente_rejeitada_com_409` | Tentativa de associar mesma chave com conteúdo divergente gera 409. | `PASSED` |
| `test_reenvio_preserva_identidade_e_conteudo_originais` | Retentativas mantêm a mesma chave de operação e o mesmo payload congelado. | `PASSED` |
| `test_criacoes_concorrentes_com_chaves_distintas_avancam_versoes_sem_colisao` | Duas criações simultâneas na conexão avançam snapshot_version sem colisão. | `PASSED` |
| `test_criacoes_concorrentes_com_mesma_chave_recuperam_mesmo_lote` | Duas criações simultâneas com mesma chave recuperam lote sem IntegrityError. | `PASSED` |
| `test_dois_executores_concorrentes_apenas_um_despacha_por_lease` | Concorrência de executores barra o segundo via lease durável com 409. | `PASSED` |
| `test_queda_apos_envio_antes_da_confirmacao_retomada_consulta_sem_reenviar` | Crash após envio recupera confirmação no conector sem reenvio duplicado. | `PASSED` |
| `test_zero_conexoes_banco_retidas_durante_chamada_ao_conector` | Medição direta no pool: zero conexões retidas durante chamada ao adaptador. | `PASSED` |
| `test_publicacao_idempotente_com_mesma_chave_recupera_lote_original_apos_mudancas_no_catalogo` | Rechamada idempotente recupera lote original após alterações no catálogo. | `PASSED` |
| `test_publicacao_executa_fora_de_transacao_de_banco_e_atualiza_monotonico` | Transações curtas locais com I/O fora de locks e monotonicidade de versão. | `PASSED` |
| `test_resultados_parciais_e_retomada_com_chave_estavel` | Falha pontual em item do lote permite retomada preservando chave estável. | `PASSED` |
| `test_tres_nichos_e_combinado_sem_imposicao_de_cozinha_ou_mesas` | Alimentação, varejo, beleza e combinado com preços vindos dos dados. | `PASSED` |

---

## 5. Salvaguardas e Compromissos Mantidos

1. **Gate S10.1 Mantido Fechado:** Nenhuma alteração nos requisitos aprovados de S10.1 (D1/R11 preservada, migração 101 intocada).
2. **Migrações Publicadas Intocadas:** A migração publicada `102_the_catalog_snapshot_freezes` não sofreu nenhuma alteração. As extensões de lease foram isoladas na nova migração `103_the_publication_batch_leases`.
3. **Decisões D2 e D8 Não Aprovadas:** Permanecem fora do código produtivo.
4. **Permissões D7:** Permanecem não concedidas a nenhum perfil ou rota.
5. **Purga Física (P12–P16):** Mantida pendente para momento posterior.
6. **Infraestrutura e Custos:** Nenhuma contratação de infraestrutura paga ou provedores externos foi efetuada.
