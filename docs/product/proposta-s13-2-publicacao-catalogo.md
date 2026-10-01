# Proposta — S13.2: Publicação Fundacional de Catálogo no Channel Hub

Data: 01 de outubro de 2026<br>
Status: **PROPOSTA TÉCNICA E PRIMEIRA FATIA FUNDACIONAL DO S13.2**<br>
Base: `620169c` em `main` (Gate interno fundacional do S10.1 concluído, CI 36916654695 verde).<br>
Cabeça de migração inicial: `101_the_channel_price_stands`; cabeça nesta fatia: `102_the_catalog_snapshot_freezes`.

---

## 1. Contexto e Objetivos

O épico S10.1 consolidou a fundação de ingresso de pedidos, normalização desacoplada de dados pessoais, preservação estrita de preços do canal (`D1/R11`), concorrência canônica de locks e reconciliação financeira preliminar.

O épico **S13.2 (Catálogo e Integrações Avançadas)** estabelece a via reversa: a publicação controlada, versionada e idempotente do catálogo do DASHEM POS para canais de venda externos (marketplaces e e-commerce).

A primeira fatia técnica do S13.2 foca exclusivamente na **fundação do executor de publicação retomável**, utilizando o conector de referência (`CONTRACT_TEST`) e respeitando rigorosamente os contratos de governança, concorrência e integridade temporal.

---

## 2. Reutilização de Entidades Existentes e Extensões Canônicas

A arquitetura do S13.2 parte estritamente dos modelos já introduzidos em `app/models/channel_catalog.py`:

1. **`ChannelCatalogOffer`:**
   - Modela o estado corrente de um produto (`product_id`) para uma conexão de merchant (`merchant_connection_id`).
   - Campos essenciais: `price`, `available`, `stock_quantity`, `desired_version` (versão almejada no POS), `published_version` (versão efetivamente confirmada pelo canal) e `last_publication_status` (`PENDING`, `SUCCEEDED`, `FAILED`).
2. **`ChannelPublicationBatch`:**
   - Representa o lote de publicação idempotente gerado para a conexão.
   - Campos canônicos: `id`, `tenant_id`, `store_id`, `merchant_connection_id`, `status` (`PENDING`, `PROCESSING`, `PARTIAL`, `SUCCEEDED`, `FAILED`), `idempotency_key`, `request_hash`, `created_by`.
   - **Extensão da Migração 102:**
     - `snapshot_version: int`: versão sequencial do snapshot/lote, **completamente desacoplada** da `desired_version` individual de cada oferta.
     - `content_hash: str` (SHA-256): hash criptográfico do conteúdo congelado de todos os itens do lote, **desacoplado** do `request_hash` (que identifica os parâmetros da requisição).
3. **`ChannelPublicationItem`:**
   - Modela cada oferta participante do lote e seu resultado específico junto ao canal.
   - Campos canônicos: `batch_id`, `offer_id`, `desired_version`, `provider_operation_key`, `status` (`PENDING`, `SUCCEEDED`, `FAILED`), `attempt_count`, `provider_result_ref`, `error_code`, `error_message`.
   - **Extensão da Migração 102:**
     - `frozen_payload: dict` (JSON): congela o payload exato (dados do produto, SKU, preço declarado, disponibilidade, atributos de nicho) enviado ao canal para aquela oferta naquele instante.

---

## 3. Invariantes Arquiteturais Estritos

### Invariante 1: Separação de Versões (Lote vs. Oferta)
A versão do snapshot/lote (`snapshot_version`) identifica o agrupamento de publicação da loja/conexão. Cada oferta individual possui seu próprio ciclo de mutação e sua própria `desired_version`. Um lote de `snapshot_version = 4` pode conter simultaneamente uma oferta em `desired_version = 7` (item modificado recentemente) e outra em `desired_version = 1` (item que nunca sofreu alteração).

### Invariante 2: Congelamento Integral por Item (`frozen_payload`)
Cada `ChannelPublicationItem` armazena no momento da criação do lote o payload estático a ser despachado. Mutações futuras no produto ou no preço local do POS **não alteram** o conteúdo congelado de lotes já criados.

### Invariante 3: Separação entre `request_hash` e `content_hash`
- `request_hash`: hash SHA-256 dos parâmetros de invocação da requisição (ex.: tenant, conexão, lista explícita de produtos solicitados, autor). Serve para garantir que reenvios com a mesma chave representam a mesma intenção de comando.
- `content_hash`: hash SHA-256 determinístico dos itens e atributos congelados no lote. Permite auditoria imediata de divergência de catálogo.

### Invariante 4: Recuperação Idempotente do Lote Original
Se uma requisição de publicação for repetida com a mesma `idempotency_key`, o executor **recupera deterministicamente o lote original e seus itens congelados**, devolvendo o estado corrente daquele lote, mesmo que produtos, estoques ou preços tenham sido alterados no banco de dados posteriormente.

### Invariante 5: Convergência Monotônica e Proteção Contra Respostas Fora de Ordem
Canais assíncronos e redes distribuídas podem entregar confirmações ou falhas fora de ordem:
1. **Confirmação antiga não publica versão nova:**
   - Se o canal confirmar com sucesso (`SUCCEEDED`) um item com `desired_version = 2`, mas a oferta no POS já estiver em `published_version = 3` (publicada por lote posterior), a versão publicada **não regride**:
     $$\text{published\_version} = \max(\text{published\_version}, \text{item.desired\_version})$$
   - O status `last_publication_status` da oferta permanece `SUCCEEDED`, mantendo a referência da versão mais avançada.
2. **Falha antiga não sobrescreve sucesso posterior:**
   - Se um item antigo com `desired_version = 1` falhar tardiamente (`FAILED`), mas a oferta já tiver sido publicada com sucesso na versão 2 (`published_version = 2`), o status do item individual no lote antigo registra `FAILED`, mas a oferta `ChannelCatalogOffer` **mantém** `published_version = 2` e `last_publication_status = SUCCEEDED`.

### Invariante 6: Preservação de Identidade da Operação em Retomadas
Cada item do lote possui uma `provider_operation_key` estável (ex.: `pub-{batch_id}-{offer_id}-{desired_version}`).
Em caso de retomada após queda de conexão ou falha parcial:
- Itens com `status == SUCCEEDED` não são reenviados;
- Itens com `status == PENDING` ou `FAILED` temporário preservam a `provider_operation_key` original, permitindo que canais que suportem deduplicação por chave operacional processem o reenvio sem duplicar itens no marketplace;
- Em caso de confirmação perdida, a consulta de status utiliza a mesma chave de operação.

### Invariante 7: Chamadas de Rede Estritamente Fora de Transações de Banco
Seguindo o princípio demonstrado em R14:
1. **Fase 1 (Transação BD Local):** Adquire ou cria lote e itens, valida conexão e merchant, congela payload, define `status = PROCESSING`, commita e encerra a transação do SQLAlchemy/PostgreSQL. Nenhuma conexão com o banco fica presa.
2. **Fase 2 (I/O de Rede Assíncrono):** Executa a chamada HTTP / protocolo do conector externo sem nenhuma transação aberta.
3. **Fase 3 (Transação BD Local):** Abre nova sessão curta, atualiza o status dos itens e do lote com os resultados recebidos, aplica as regras de versão monotônica em `ChannelCatalogOffer` e comita.

---

## 4. Cobertura dos Três Nichos e Negócios Combinados

O Commerce OS atende múltiplos perfis de comércio. O catálogo de canais deve respeitar os três nichos aprovados:
1. **Alimentação (`FOOD_SERVICE`):** Produtos prontos para consumo, combos, ingredientes e observações de preparo;
2. **Varejo (`RETAIL`):** Produtos por código de barras / SKU, controle de estoque unitário e variações físicas, **sem imposição de cozinha, mesas (`table_service`) ou produção**;
3. **Revenda de Beleza (`BEAUTY_RESELLER`):** Cosméticos, fragrâncias e kits por marca/linha, com atributos específicos e estoque fracionado, **sem imposição de restaurante**;
4. **Tenant Combinado (`FOOD_SERVICE` + `RETAIL`):** Operação híbrida (ex.: cafeteria com empório de cafés especiais e produtos artesanais) onde produtos de varejo não geram tickets de cozinha nem exigem área de mesas.

Os preços publicados originam-se **estritamente dos dados e fixtures** (preço da oferta ou do produto cadastrado). Não há preços comerciais hardcoded no código e não há fallback inventado caso o canal exija parâmetros não informados.

---

## 5. Limites Expressos e Salvaguardas

1. **Permissões D7:** Permanecem não concedidas a nenhum perfil padrão.
2. **Decisões D2 e D8:** Permanecem propostas não aprovadas para implementação; nenhuma rotina de cancelamento automático ou hook outbound não autorizado é acionado.
3. **Purga Física (P12–P16):** Não implementada nesta fatia; mantida para etapa posterior a G2.
4. **Infraestrutura Paga:** Nenhum serviço ou provedor com custo foi contratado.
5. **Canais Comerciais:** A execução é realizada e comprovada contra o adaptador de referência (`CONTRACT_TEST`).
