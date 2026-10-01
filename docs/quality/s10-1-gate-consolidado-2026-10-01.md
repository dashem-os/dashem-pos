# S10.1 — Gate Interno Consolidado do Channel Hub

Data de consolidação: 01 de outubro de 2026<br>
Status de Publicação: **D1/R11 PUBLICADA E CONFIRMADA EM PRODUÇÃO** (commits `4b5e312`, `9a6543c` e `620169c`, CI 36916654695 verde nos 4 jobs)<br>
Decisão do Gate: **S10.1 CONCLUÍDO NO GATE INTERNO FUNDACIONAL**<br>
Fundamentação: A publicação funcional da migração 101 e a preservação de preços do canal (D1/R11) estão aprovadas, publicadas e ativas. O alinhamento das provas foi rigorosamente concluído e validado em CI verde (run 36916654695, 4 jobs):
1. **R19:** Controle verdadeiro de idempotência por linha comprovado (implementação normal passa; mutante via monkeypatch no caminho de atualização cria item ativo duplicado mantendo original e reprova com AssertionError no detector comum `assert_active_lines_and_items`; substituição legítima com 2 ativos e 1 cancelado passa; duas linhas distintas do mesmo produto passam; controle de commit prematuro conservado separadamente como controle de atomicidade);
2. **P8:** Comprovação estrita por comparação de snapshot de estado antes e depois da ingestão/atualização, incluindo registros prévios de CRM (`customers`), fidelidade/crédito (`customer_credit_policies`) e fiscal (`fiscal_documents`, `fiscal_events`), demonstrando ausência de mutação ou criação fora de `channel_order_contacts`;
3. **R20:** Evidência regenerada com roteiro final (`hom09-canais.json` com timestamp `2026-10-01T19:41:34.529Z`), contendo `order_id` verificado na API (`d7210e9a-5d54-4552-952b-be771d928fdc`), 10 telas capturadas, 0 falhas, e separação explícita entre a travessia no navegador (Chopp R$ 18,50) e os cenários backend (−R$ 2,00 e −R$ 3,50 com complementos e subsídios);
4. **D2, D8 e concessões de D7:** Mantidas como **propostas NÃO APROVADAS para implementação**, com contradições conceituais expurgadas (eliminação de `OPEN` para tickets de produção, distinção entre notificações definitivas e solicitações negociáveis, separação de efeitos financeiros segundo iFood Financial API v2 e exigência de acesso assistido temporário e auditado para suporte);
5. **Diagnóstico S13.2:** Ancorado nas entidades existentes em `app/models/channel_catalog.py` (`ChannelCatalogOffer`, `ChannelPublicationBatch`, `ChannelPublicationItem`), separando snapshot de desired_version, frozen_payload e request_hash de content_hash.

Conforme previsto na proposta original (§7, itens 7 a 9), permanecem expressas as seguintes pendências operacionais e etapas posteriores:
1. **Retenção sem purga física:** P12–P16 pertencem à etapa posterior de purga (§7, item 9), a ser desenvolvida após a formalização do ciclo de backups (G2).
2. **D2 operacional NÃO aprovada:** Cancelamento com item em preparo permanece retido no comportamento conservador comprovado (`NEEDS_REVIEW` com código `PREPARATION_STARTED`), preservando produção e cobertura financeira;
3. **Avisos automáticos D8 NÃO aprovados:** Nenhuma emissão automática de aviso ao canal está habilitada; avisos continuam restritos ao acionamento explícito;
4. **Concessão de D7 NÃO aprovada:** As 4 permissões especiais existem no catálogo sem concessão a perfis padrão; a leitura de dados de contato segue bloqueada;
5. **Canais comerciais não homologados:** A fundação foi provada contra o adaptador de referência (`CONTRACT_TEST`).

---

## 1. Separação de Evidências de Publicação

1. **Repositório Git e Integração Contínua (CI):**
   - Commit de publicação inicial: [`4b5e312`](https://github.com/dashem-os/dashem-pos/commit/4b5e312e72b7fbbd189e6cbc64f569d035c21b1d) em `main` (CI 36861234960).
   - Commit de consolidação probatória: [`9a6543c`](https://github.com/dashem-os/dashem-pos/commit/9a6543c80e1bbbe9635b71db3f05a1e285a8d462) em `main` (CI 36901102911).
   - Commit de fechamento formal do gate: [`620169c`](https://github.com/dashem-os/dashem-pos/commit/620169c) em `main` (CI [36916654695](https://github.com/dashem-os/dashem-pos/actions/runs/36916654695) verde nos 4 jobs: Backend 4m4s, E2E 1m20s, Frontend 30s, Alembic 54s).
2. **Deploy Frontend (Vercel):**
   - Deployments associados com estado `success` no target de produção.
   - URL de produção: `https://dashem-pos.vercel.app` (HTTP 200).
3. **Deploy Backend API (Render):**
   - Endpoint de produção: `https://dashem-pos-api.onrender.com/health` respondendo HTTP 200 com ambiente `production`.
4. **Ressalva de Produção (Sem Prova Direta):**
   - A resposta HTTP 200 no `/health` comprova que o serviço web do Render está saudável, mas **não constitui prova direta do SHA exato da imagem em execução** nem da aplicação efetiva da migração 101 no banco de dados de produção do Supabase. O executor não dispõe de credenciais de introspecção na infraestrutura do Render e do Supabase para coletar essa evidência direta.

---

## 2. Matriz Integral dos Critérios R e P

A matriz abaixo relaciona todos os critérios R1–R20 e P1–P21 previstos na proposta original (`proposta-s10-1-channel-hub.md`, §§6 e 7), indicando para cada um a prova específica, o resultado e os limites declarados da verificação.

### A. Requisitos de Ingestão, Concorrência e Avisos (R1 a R20)

| ID | Requisito da Proposta (§6.1) | Prova Específica (Arquivo / Linha) | Resultado | Limite da Prova |
|---|---|---|---|---|
| **R1** | Dois consumidores reivindicam o mesmo evento: um aplica, o outro não repete (H2). | `test_channel_inbox.py:197` (`test_dois_processadores_ao_mesmo_tempo_um_so_aplica`) | `PASSED` | Concorrência de threads com barreira determinística na mesma instância de processo. |
| **R2** | Parada depois de criar o pedido e antes das linhas: retomada completa sem duplicar (H2, H3). | `test_channel_inbox.py:157` (`test_pedido_e_linhas_nascem_juntos_e_uma_queda_no_meio_nao_deixa_metade`) | `PASSED` | Falha simulada por exceção na transação; PostgreSQL descarta transação não confirmada; não simula queda forçada de processo SO (`kill -9`). |
| **R3** | Parada depois das linhas e antes de gravar a chave de ordem: retomada sem duplicar (H2, H3). | `test_channel_inbox.py:199` (`test_r3_parada_depois_das_linhas_e_antes_de_gravar_chave_de_ordem_retomada_sem_duplicar`) | `PASSED` | Interrupção injetada em `_advance` após inserção das linhas; rollback desfaz alterações sem vazar linhas nem chave; retomada aplica uma única vez. |
| **R4** | Canal reenvia o mesmo evento por confirmação perdida: nenhuma linha nova, nenhum efeito (H1, H4). | `test_channel_ingress.py:93` (`test_o_mesmo_evento_repetido_nao_cria_nada_e_o_divergente_fica_so_registrado`) | `PASSED` | Resposta `DUPLICATE` baseada no hash do payload assinado; nenhum reprocessamento disparado. |
| **R5** | Mesmo identificador com conteúdo diferente: divergência registrada, nada aplicado (H4). | `test_channel_ingress.py:93` (`test_o_mesmo_evento_repetido_nao_cria_nada_e_o_divergente_fica_so_registrado`) | `PASSED` | Resposta `DIVERGENT`; trilha imutável em `audit_events` registra ocorrência sem dados pessoais; conteúdo original em banco preservado. |
| **R6** | Atualização com linha nova, alterada e removida, aplicada por linha externa (H3, H4). | `test_channel_inbox.py:287` (`test_atualizacao_compara_linhas_externas_e_a_antiga_nao_regride`) | `PASSED` | `ORDER_UPDATED` adiciona, atualiza e cancela linhas existentes no PDV por matching de chave externa; não duplica itens. |
| **R7** | Atualização mais antiga que a aplicada: `SUPERSEDED`, pedido intacto (H5). | `test_channel_inbox.py:287` (`test_atualizacao_compara_linhas_externas_e_a_antiga_nao_regride`) | `PASSED` | Evento com sequência anterior à `last_order_key` é classificado como `SUPERSEDED` e descartado sem mutação no pedido. |
| **R8** | Cancelamento sem preparo cancela; com item em preparo, `NEEDS_REVIEW` visível (H6). | `test_channel_inbox.py:342` (`test_cancelamento_sem_preparo_encerra_com_preparo_vira_revisao_e_depois_do_fim_nada_muda`) | `PASSED` | Sem item em preparo $\rightarrow$ cancela pedido e alocações; com ticket em `ACCEPTED`/`PREPARING` $\rightarrow$ retido em `NEEDS_REVIEW` (`PREPARATION_STARTED`). Separado da esteira humana D2. |
| **R9** | Atualização depois do estado terminal: registrada, não aplicada (H5, H6). | `test_channel_inbox.py:342` (`test_cancelamento_sem_preparo_encerra_com_preparo_vira_revisao_e_depois_do_fim_nada_muda`) | `PASSED` | Evento recebido após `terminal_at` (`CONCLUDED` ou `CANCELED`) é registrado como `SUPERSEDED`; pedido terminal intocado. |
| **R10** | Item sem mapeamento: quarentena nomeada; depois do mapeamento, "Retomar" aplica (H2, H11). | `test_channel_inbox.py:452` (`test_quarentena_retomada_por_pessoa_nao_alonga_o_prazo_e_evento_vencido_expira`) | `PASSED` | Item não vinculado vai para `QUARANTINED` (`ITEM_NOT_MAPPED`); após associação de catálogo, retomada aplica e abre o pedido no PDV. |
| **R11** | Valores externos preservados sem alterar catálogo local, diferenciação entre `MARKETPLACE`, `LOCAL` e `UNKNOWN` (`ORDER_PAID_IN_MARKETPLACE` vs. `ORDER_PAYMENT_ORIGIN_UNKNOWN`), bloqueio sob reserva/liquidação (`CHANNEL_PAYMENT_ORIGIN_CONFLICT`), entrega em itens gratuitos, concorrência e hierarquia canônica de locks sem deadlocks 40P01 (H7, H17). | `test_r11_concurrency_matrix.py` (7 testes), `test_channel_inbox.py:583-1624` e `test_channel_contract.py` | `PASSED` | Preço do canal em `OrderItem.unit_price`, acervo em `ProductPrice` preservado, obrigação com entrega, bloqueio de cobrança indevida, protocolo transacional canônico verificado contra PostgreSQL isolado. |
| **R12** | Aviso entregue só com confirmação; transitório $\rightarrow$ `RETRY`; esgotado $\rightarrow$ `DEAD_LETTER`; "Reenviar" autorizado (H8). | `test_channel_outbound.py:120` | `PASSED` | Confirmação do canal $\rightarrow$ `DELIVERED`; erro de rede transitório $\rightarrow$ `RETRY`; esgotamento $\rightarrow$ `DEAD_LETTER`; reenvio manual reutiliza a mesma chave. |
| **R13** | Tempo esgotado no aviso: repetição com a mesma chave, ou consulta antes (H8). | `test_channel_outbound.py:210` | `PASSED` | Repetição de envio preserva deterministicamente a `Idempotency-Key` original da mensagem outbound. |
| **R14** | Latência da venda local sob indisponibilidade do canal: ausência de regressão interna nas condições medidas (H10). | [`r14-local-sale-latency.json`](evidence/s10-1-2026-09-29/r14-local-sale-latency.json) e `test_channel_outbound.py:549` | `PASSED` | Medição em 15 amostras locais contra PostgreSQL 15 real (baseline p50 310,55 ms vs. bloqueio p50 308,56 ms; `checkedout == 0` observado; controle reprova em 810,20 ms). Comprovado como ausência de regressão interna nas condições medidas; não é medição contra marketplace real nem SLA de escala. |
| **R15** | Ingresso de merchant do tenant A não alcança tenant B; corpo com tenant alheio é ignorado (H9). | `test_channel_ingress.py:160` | `PASSED` | RLS e resolução server-side da conexão garantem isolamento estrito; dados de A invisíveis para B. |
| **R16** | Assinatura sobre bytes: mesmo conteúdo reserializado não passa (H9). | `test_channel_ingress.py:123` | `PASSED` | Assinatura HMAC-SHA256 validada sobre os bytes exatos (`raw bytes`); reserialização com chaves reordenadas devolve `401 SIGNATURE_INVALID`. |
| **R17** | Merchant sem conexão autorizada: recusado sem dado pessoal nem payload gravado (H9, H12, H17). | `test_channel_ingress.py:139` | `PASSED` | Conexão ausente ou não validada rejeita eventos com `MERCHANT_NOT_CONNECTED`; nada é salvo no banco de dados. |
| **R18** | Capacidade não declarada não é chamada e aparece como ausente (H11). | `test_channel_screen_facts.py:80` e `test_channel_ingress.py:197` | `PASSED` | Adaptador sem capacidade declarada não expõe rota correspondente e relata ausência na consulta gerencial. |
| **R19** | Controle negativo: idempotência por linha quebrada de propósito — R2 tem de ver a duplicata (medida). | `test_channel_inbox.py` (`test_r19_controle_idempotencia_por_linha_quebrada_de_proposito_reprova_duplicata`) | `PASSED` | Implementação normal com identificação estável de linhas atualiza quantidade in-place e passa no detector comum; mutante quebrado no caminho de atualização cria item ativo adicional preservando original (duplicação ativa de itens), fazendo o detector reprovar com `AssertionError`; substituição legítima (2 ativos, 1 cancelado) e duas linhas do mesmo produto passam no detector. Controle de atomicidade preservado em `test_controle_atomicidade_commit_prematuro_encontra_pedido_parcial`. |
| **R20** | Travessia autenticada completa na interface com gestora e leitora (H8, H11). | [`hom09_canais_de_venda.cjs`](file:///D:/Workplace/Dashem%20POS/frontend/e2e/presentation/hom09_canais_de_venda.cjs), [`hom09-canais.json`](evidence/s10-1-2026-10-01/hom09-canais.json) | `PASSED` | 17 etapas, 10 telas capturadas, 0 falhas; gestora opera e leitora recebe HTTP 403 estrito. Evidência auditada com `order_id` verificado na API (`d7210e9a-5d54-4552-952b-be771d928fdc`). Aferição visual e ações operacionais no navegador; garantias de catálogo e finanças demonstradas no backend. |

---

### B. Requisitos de Retenção e Dados Pessoais (P1 a P21)

| ID | Requisito da Proposta (§6.2) | Prova Específica (Arquivo / Linha) | Resultado | Limite da Prova |
|---|---|---|---|---|
| **P1** | Pedido de canal fica terminal: `terminal_at` gravado; payload aplicado sem quarentena recebe terminal + 30 dias e contato recebe terminal + 90 dias na mesma transação. Antes disso, ambos nulos e contados como "aguardando estado terminal", com a idade (H14). | `test_channel_inbox.py:410` (`test_estado_terminal_ancora_os_prazos_do_payload_e_do_contato`) | `PASSED` | Base `ESTADO_TERMINAL` mantém prazos nulos enquanto pedido está aberto; ao concluir, calcula e grava prazos simultaneamente na mesma transação. |
| **P2** | Ao persistir, todo evento recebe `retention_until` = recepção + 30 dias com base `RECEPCAO`, na mesma transação; nenhum evento persiste sem prazo (H14). | `test_channel_ingress.py:63` | `PASSED` | Ingestão atribui imediatamente prazo de 30 dias na persistência inicial. Prazos em repouso; expurgo físico depende de purga. |
| **P3** | Marcadores de nome, telefone e endereço aparecem **só** em `channel_inbox_events.raw_payload` e em `channel_order_contacts` (H13, H17). | `test_channel_inbox.py:500` (`test_a_pessoa_mora_so_no_contato_e_evento_sem_pedido_nao_cria_contato`) | `PASSED` | Varredura em 8 tabelas/campos comprova ausência dos marcadores fora das entidades segregadas. Baseada em marcadores conhecidos. |
| **P4** | Aviso ao canal para pedido com contato: outbox e `published_events` levam só identificadores (H17). | `test_channel_outbound.py:280` | `PASSED` | Fila de saída trafega exclusivamente IDs de correlação, sem dados pessoais de contato. |
| **P5** | Nenhum DTO ou rota grava `retention_until`, campos de legal hold ou `redaction_method` — tentativa pelo corpo é ignorada ou recusada (H18). | `test_channel_ingress.py:63` e `:271` | `PASSED` | Injeção de prazo e base no payload é ignorada pelo servidor; varredura estática de rotas confirma ausência de parâmetros para gravação desses campos. |
| **P6** | Nenhuma rota devolve nome, telefone ou endereço; nenhuma rota registra hold, estende retenção ou dispara limpeza (H18). | `test_channel_screen_facts.py:150` e `hom09_canais_de_venda.cjs` | `PASSED` | Respostas de API omitem dados de contato; rotas de mutação de hold e expurgo não existem na API ativa. |
| **P7** | Restrição de banco: hold com algum dos cinco campos faltando é recusado (H16). | `test_channel_ingress.py:213` (`test_legal_hold_so_existe_completo`) | `PASSED` | CheckConstraint `ck_legal_hold_completeness` gera `IntegrityError` se qualquer um dos 5 campos de hold for nulo; gravação completa é aceita. |
| **P8** | Ingestão de pedido de canal não cria nem altera cliente de CRM, fidelidade ou dado fiscal (H19). | `test_channel_inbox.py` (`test_p8_ingestao_de_pedido_de_canal_nao_cria_nem_altera_crm_fidelidade_e_fiscal`) | `PASSED` | Comparação estrita de snapshots antes e depois da ingestão/atualização (com clientes de CRM, fidelidade/crédito e documentos/eventos fiscais pré-existentes): contagens inalteradas, registros existentes não mutados e dados do canal restritos exclusivamente a `ChannelOrderContact`. |
| **P9** | Payload com marcador que provoca erro de normalização: o motivo de quarentena tem código e texto seguro, sem o marcador (H17). | `test_channel_inbox.py:500` (`test_a_pessoa_mora_so_no_contato_e_evento_sem_pedido_nao_cria_contato`) | `PASSED` | Marcador plantado no campo inválido não aparece em `quarantine_reason` nem na interface; código seguro atribuído. |
| **P10** | Tela e diagnóstico mostram vencidos aguardando limpeza e a última limpeza; com zero execuções, dizem isso (H20). | `test_channel_screen_facts.py:100` e telas 6 e 9 da travessia R20 | `PASSED` | Exibição de contagens agregadas de pedidos aguardando terminal e aviso explícito de que a rotina de limpeza ainda não existe. |
| **P11** | Nenhuma chamada de log ou `print` do backend passa dados pessoais; controle com seis vazamentos plantados e três chamadas seguras (H17). | `test_no_personal_data_in_logs.py` | `PASSED` | Análise sintática AST em todo o código backend reprova chamadas com dados sensíveis; controle calibrado com vazamentos plantados. |
| **P12 a P16** | Purga do payload, redação de contato, respeito a legal hold, re-purga pós restore e controle negativo (H13, H15, H16). | §7, item 9 da proposta | **Reservado para etapa posterior (Purga)** | O mecanismo físico de expurgo em lote (`channel_purge_service`) e o restore simulado (P15) não foram implementados nesta fatia fundacional. Os prazos são atribuídos e contabilizados em repouso. Não bloqueia o gate interno. |
| **P17** | Evento em quarentena por falta de mapeamento, mapeado e aplicado depois, mantém recepção + 30 dias; o contato criado na aplicação conta do terminal (H14). | `test_channel_inbox.py:452` (`test_quarentena_retomada_por_pessoa_nao_alonga_o_prazo_e_evento_vencido_expira`) | `PASSED` | Retomada da quarentena preserva a base `RECEPCAO` e o prazo original do evento; contato nasce com base no terminal. |
| **P18** | Evento nunca aplicado cujo prazo venceu vira `EXPIRED`, definitivo; "Retomar" não o alcança (H14). | `test_channel_inbox.py:452` (`test_quarentena_retomada_por_pessoa_nao_alonga_o_prazo_e_evento_vencido_expira`) | `PASSED` | `inbox.expire_overdue()` move evento com prazo vencido para `EXPIRED`; tentativa de retomar devolve `409 EVENT_EXPIRED`. |
| **P19** | Prazo só encurta: nenhuma transição do fluxo alonga `retention_until`, exceto a troca única de `RECEPCAO` para `ESTADO_TERMINAL` de evento aplicado sem quarentena; controle alonga de propósito e o teste reprova (H14). | `test_channel_inbox.py:452` (com o controle `_lengthened` em linha 428) | `PASSED` | Todas as transições verificadas não alongam o prazo; controle negativo detecta alongamento artificial plantado. |
| **P20** | As quatro permissões da D7 existem no catálogo e **nenhum perfil** as recebe; nenhuma rota as exige nem as contorna; controle concede uma a um perfil de propósito e o teste reprova (H18). | `test_channel_ingress.py:252` (`test_as_permissoes_da_d7_existem_e_ninguem_as_recebe_antes_de_definidas_e_testadas`) | `PASSED` | Catálogo contém as 4 permissões; 0 perfis ou pessoas as possuem; controle negativo acusa concessão plantada; rotas HTTP não as nomeiam. |
| **P21** | Evento que nunca vira pedido não cria linha de contato; nome, telefone e endereço dele existem só no payload (H13, H14). | `test_channel_inbox.py:500` (linha 540) | `PASSED` | Eventos que terminam em quarentena não geram registros em `channel_order_contacts`; apenas o evento aplicado gera contato. |

---

### C. Dependências Externas (G1, G2, G3)

A proposta original estabeleceu três dependências externas de governança e infraestrutura:
- **G1 — Validação jurídica e de privacidade (§4.2):** Os prazos adotados (30 dias para payload bruto e 90 dias pós-terminal para dados de contato) constituem uma política técnica interna inicial do Commerce OS. Enquanto não houver validação formal por assessoria jurídica/DPO, nenhuma comunicação comercial ou garantia contratual externa declarando conformidade estrita pode ser emitida.
- **G2 — Ciclo de expiração de backups do provedor (§4.2):** O ciclo de retenção e expiração física de dumps e snapshots gerenciados pelo Supabase segue a política do plano contratado pela administração. A purga em nível de aplicação atinge o armazenamento primário em banco de dados; a eliminação definitiva no ciclo de vida dos backups depende da rotação natural do provedor.
- **G3 — Retenção de logs em nuvem (§4.2):** A conferência dos planos vigentes do Render e do Supabase contra o teto desejado de 14 dias de retenção de logs cabe aos administradores das contas dos provedores. No nível de software, o guarda AST (P11) impede deterministicamente a inserção de novos dados pessoais nos logs do backend.

---

## 3. Limites e Delimitação da Travessia R20

A travessia autenticada R20 (`hom09_canais_de_venda.cjs`) foi executada com sucesso contra o ambiente integrado local, com limites e separações rigorosamente declarados:
- **Valores enviados pelo roteiro da travessia:** Produto `CHOPE-500` com preço unitário declarado pelo canal de `R$ 18,50`, quantidade `2`, taxa de entrega de `R$ 7,00`, total declarado de `R$ 44,00` e pagamento `PAID_ONLINE` (normalizado para `MARKETPLACE`).
- **Valores verificados pela API no percurso:** A consulta `GET /api/v1/orders/{order_id}` atesta que o pedido foi criado com `order_id` registrado no artefato final (`d7210e9a-5d54-4552-952b-be771d928fdc`), `items[0].unit_price == "18.5000"` e `items[0].quantity == "2.0000"`.
- **Separação estrita entre o exemplo da travessia e os cenários backend:** O percurso no navegador afere exclusivamente a visualização e operação do pedido simples de Chopp (R$ 18,50). As regras complexas de cálculo, divergências, complementos e bloqueios foram comprovadas exclusivamente pela suíte automatizada do backend e **não são atribuídas ao navegador**:
  - `test_r11_pedido_registra_valor_do_canal_preserva_oferta_local_com_complemento_e_atualiza_so_preco`: comprova a oferta local de `ITEM-A` (`ProductPrice` R$ 18,50 com complemento `COMP-QUEIJO` a R$ 3,50 = R$ 22,00 unitário $\times$ 2 = R$ 44,00) combinada com `ITEM-B` (R$ 9,90 $\times$ 1 = R$ 9,90), totalizando itens locais de R$ 53,90. Frente aos valores declarados pelo canal (`ITEM-A` bruto R$ 25,00 com desconto de linha R$ 4,00 $\rightarrow$ líquido R$ 46,00; `ITEM-B` R$ 8,90; entrega R$ 7,00, desconto de pedido R$ 3,00 e subsídio R$ 5,00 $\rightarrow$ mercadoria efetiva do canal R$ 51,90 e total R$ 58,90), a diferença verificada é inicialmente de **−R$ 2,00** (`difference_amount == Decimal("-2.0000")`), e de **−R$ 3,50** após atualização de preços (`difference_amount == Decimal("-3.5000")`), com preservação estrita do catálogo local (`ProductPrice` inalterado em R$ 18,50 e R$ 9,90). *(Ajuste formal: o relatório anterior citava equivocadamente uma diferença de R$ 1,00; os valores reais do cenário verificado são −R$ 2,00 inicial e −R$ 3,50 na atualização)*;
  - `test_r11_valores_inseguros_ou_inconsistentes_vao_para_revisao_sem_usar_preco_local`: valida consistência de descontos, subsídios e totais declarados, direcionando divergências a `NEEDS_REVIEW`;
  - `test_r11_protege_pedido_marketplace_contra_cobranca_local_e_bloqueia_desconto_de_cabecalho_sob_reserva`: comprova bloqueio de cobrança local indevida com HTTP `409 ORDER_PAID_IN_MARKETPLACE`;
  - `test_r11_concurrency_matrix.py` (7 testes): comprova a ordem canônica de locks sem deadlocks 40P01 sob concorrência intensa.
- **Autenticação:** Sessão iniciada com JWT de teste assinado localmente com `AUTH_TEST_SECRET`, contra API em `AUTH_MODE=test` e concessões no PostgreSQL isolado. Não comprova login interativo com formulário de usuário/senha nem a infraestrutura do Supabase Auth em produção.
- **Responsividade:** A varredura nas larguras 1366 px, 1024 px, 768 px e 390 px afere estritamente a ausência de palavras partidas ao meio (`palavrasPartidas`), sem afirmar ausência universal de defeitos de layout.

---

## 4. Análise Técnica e Desenho Preliminar de D2 (Proposta NÃO Aprovada para Implementação)

> [!WARNING]
> **Status de D2: PROPOSTA NÃO APROVADA PARA IMPLEMENTAÇÃO.**
> O comportamento conservador da fundação permanece ativo: cancelamento com preparo iniciado move o evento para `NEEDS_REVIEW` com código `PREPARATION_STARTED`, mantendo o pedido do PDV e os tickets de produção intocados até intervenção humana autorizada.

### A. Diagnóstico da Realidade Operacional e do Canal
1. **Notificação Definitiva vs. Solicitação Negociável:**
   - Em plataformas como o iFood, o evento de cancelamento unilateral após determinado ponto operacional constitui uma **notificação unilateral e definitiva**: o cancelamento já foi consumado no canal e o cliente não receberá a refeição. O sistema local **não pode simplesmente descartar (`DISCARDED`) uma notificação definitiva** fingindo que ela não existiu; a notificação reflete um fato externo irrevogável.
   - Em contrapartida, quando o canal envia uma **solicitação de cancelamento** (`CANCELLATION_REQUESTED`), abre-se janela de negociação em que o lojista pode aceitar ou recusar formalmente antes da consolidação.
2. **Efeitos Financeiros e Separação de Domínios (iFood Financial V2):**
   - **Não se deve deduzir ausência de repasse apenas do cancelamento do pedido.** A [documentação financeira do iFood (Financial API v2)](https://developer.ifood.com.br/en-US/docs/guides/financial/v2) trata os impactos financeiros separadamente do ciclo de vida operacional: pedidos cancelados com preparo já iniciado podem ensejar contestação, ressarcimento/indenização parcial ao restaurante, cobrança de taxas de cancelamento ou estorno posterior via conciliação de repasses (`MarketplaceSettlement`).
   - Portanto, a resolução operacional local de interromper o preparo na cozinha não pode disparar de forma automática o desfazimento precipitado de reservas ou assumir ausência de compensação.
3. **Estados Reais do Modelo de Dados (Correção de Enums):**
   - O modelo `ProductionTicket` transiciona estritamente entre os estados do enum `ProductionTicketStatusEnum`: `NEW`, `ACCEPTED`, `PREPARING`, `READY`, `DELIVERED` e `CANCELED`. **Não existe estado `OPEN` para tickets de produção** (o estado `OPEN` pertence a `Order.status`).
   - Enquanto o cancelamento permanece em `NEEDS_REVIEW`, o `Order` segue `OPEN` e os tickets de produção seguem no seu estado corrente na cozinha (`ACCEPTED` ou `PREPARING`).
   - Se o cancelamento for aceito pelo lojista, o ticket transiciona para `CANCELED` e o pedido para `CANCELED`; se o lojista recusar uma solicitação negociável ou registrar ciência da perda interna, a produção é tratada operacionalmente (ex.: interrompida para evitar desperdício de insumos).
4. **Preservação Estrita da Hierarquia Canônica de Locks de R11:**
   - Todo fluxo de cancelamento que alcance entidades financeiras deve obedecer à **ordem canônica de bloqueios completa de R11**:
     $$\text{PaymentIntent (N1)} \rightarrow \text{CheckoutNegotiation (N2)} \rightarrow \text{TableSession (N3)} \rightarrow \text{ServiceTable (N4)} \rightarrow \text{Order (N5)} \rightarrow \text{ExternalOrderMapping (N6)} \rightarrow \text{OrderItem (N7)}$$

### B. Fluxo Operacional Preliminar em Estudo (Não Implementado)

```
                         [ ORDER_CANCELLED / Solicitação recebida ]
                                             │
                                (Preparo já iniciado na cozinha?)
                                             │ SIM
                                             ▼
                                  [ NEEDS_REVIEW gravado ]
                             (Código: PREPARATION_STARTED)
                      (Order segue OPEN; Ticket segue ACCEPTED/PREPARING)
                                             │
                   ┌─────────────────────────┴─────────────────────────┐
                   ▼                                                   ▼
     [ Alternativa A: Aceitar / Confirmar ]              [ Alternativa B: Recusar / Registrar Perda ]
     • Ação autorizada com justificativa auditada.       • Aplicável a solicitações negociáveis ou
     • ProductionTicket -> CANCELED                      • Registro de perda com despacho/disputa.
     • Order no PDV -> CANCELED                          • ProductionTicket -> CANCELED ou segue PREPARING
     • Liquidação/estorno tratado via conciliação fiscal • Order no PDV segue conforme decisão
     • Evento na inbox -> APPLIED                        • Notificação ao canal se suportado
```

---

## 5. Matriz de Avisos Outbound ao Canal (D8 — Proposta NÃO Aprovada para Implementação)

> [!WARNING]
> **Status de D8: PROPOSTA NÃO APROVADA PARA IMPLEMENTAÇÃO.**
> Nenhuma emissão automática outbound está ativada em produção. Avisos continuam manuais e restritos ao endpoint explícito.

Para estruturar a futura decisão **D8** (quais transições do pedido geram avisos automáticos ao canal) sem ativar emissões precipitadas, define-se a seguinte matriz de comportamento:

| Evento Local do Ciclo de Vida | Mensagem Outbound | Condição de Enfileiramento | Prevenção de Eco (Anti-Echo) |
|---|---|---|---|
| Ticket aceito na cozinha (`ACCEPTED`) | `ORDER_ACCEPTED` | Canal declara `ORDER_STATUS_OUTBOUND` | Não aplicável (evento local). |
| Ticket pronto para entrega (`READY`) | `ORDER_PREPARED` | Canal declara `ORDER_STATUS_OUTBOUND` | Não aplicável (evento local). |
| Despacho com entregador (`DISPATCHED`) | `ORDER_DISPATCHED` | Canal declara `ORDER_STATUS_OUTBOUND` | Não aplicável (evento local). |
| Pedido cancelado no PDV (`CANCELED`) | `ORDER_CANCELLED` | Canal declara `ORDER_STATUS_OUTBOUND` | **ESTRITA:** Se a transição para `CANCELED` tiver sido provocada por um webhook de entrada originado do próprio canal (`ORDER_CANCELLED`), o emissor outbound **nunca** gera aviso de cancelamento para o canal, prevenindo loops de eco. |

---

## 6. Proposta de Concessões por Perfil (D7 — Proposta NÃO Aprovada para Implementação)

> [!WARNING]
> **Status de D7: PROPOSTA NÃO APROVADA PARA IMPLEMENTAÇÃO.**
> As 4 permissões continuam sem concessão padrão. Qualquer acesso concedido a suporte técnico no futuro deve preservar estritamente a decisão arquitetural consolidada: **acesso assistido, temporário, restrito ao tenant e auditado**.

| Permissão | Finalidade Operacional | Perfil Recomendado | Justificativa e Salvaguardas |
|---|---|---|---|
| `channel.order_contact.read` | Visualizar nome, telefone e endereço para expedição e entrega. | **Operador de Delivery / Expedição** (`ORDER_DISPATCHER` ou concessão nominal) | Restrita à janela operacional do pedido (até o estado terminal). Não concedida a perfis de garçom ou atendente de balcão. Toda leitura gera registro nominal em `audit_events`. |
| `channel.legal_hold.manage` | Aplicar ou liberar `legal_hold` sobre eventos, evidências ou contatos em disputa judicial. | **Gerente de Loja / Administrador** (`STORE_MANAGER`, `TENANT_ADMIN`) | Exige fornecimento obrigatório dos 5 campos estruturados (motivo, processo, responsável, revisão). Não delegável a operadores comuns. |
| `channel.retention.extend` | Estender prazo de retenção de registro além da política padrão por necessidade administrativa. | **Administrador do Tenant** (`TENANT_ADMIN`) | Ação excepcional. Requer motivo em código e prazo delimitado. Auditada. |
| `channel.retention.purge` | Disparar manualmente a rotina de limpeza física de registros vencidos. | **Acesso Assistido de Suporte / Admin do Tenant** | Ação destrutiva definitiva. Preserva a exigência de acesso assistido, temporário, auditado e restrito ao tenant. Não concedido de forma irrestrita. |

---

## 7. Diagnóstico e Preparação para S13.2 (Estruturas Existentes e Modelo de Publicação)

Com o gate interno fundacional do S10.1 concluído, o diagnóstico para o épico **S13.2 (Catálogo e Integrações Avançadas)** estabelece as bases sobre o código já existente no backend, antes de qualquer início de codificação:

1. **Estruturas de Dados Já Existentes (`app/models/channel_catalog.py`):**
   O próximo executor deve partir estritamente dos modelos já introduzidos no repositório:
   - **`ChannelCatalogOffer`:** Rastreia cada item publicado por conexão (`merchant_connection_id`, `product_id`), contendo `price`, `available`, `stock_quantity`, versão desejada (`desired_version: int`), versão publicada confirmada (`published_version: int`) e o status da última tentativa (`last_publication_status: PublicationItemStatusEnum` — `PENDING`, `SUCCEEDED`, `FAILED`);
   - **`ChannelPublicationBatch`:** Modela o lote de publicação idempotente (`merchant_connection_id`, `status: PublicationStatusEnum`, `idempotency_key`, `request_hash`, `created_by`);
   - **`ChannelPublicationItem`:** Registra o resultado individual por item do lote (`batch_id`, `offer_id`, `desired_version`, `provider_operation_key`, `status: PublicationItemStatusEnum`, `attempt_count`, `provider_result_ref`, `error_code`, `error_message`).

2. **Relação com o Snapshot Imutável de Catálogo:**
   Caso a fatia de S13.2 introduza um snapshot imutável (ex.: `CatalogPublicationSnapshot`), sua relação com os modelos existentes fica expressamente definida:
   - O snapshot imutável congela a árvore completa da oferta de delivery (produtos, categorias, complementos e regras de visibilidade) no instante em que o lote é montado;
   - O hash do snapshot imutável ancora o campo `request_hash` de `ChannelPublicationBatch`;
   - Cada oferta contemplada no lote gera um `ChannelPublicationItem` que referencia `ChannelCatalogOffer.id` com `desired_version = snapshot.version`;
   - O conector externo transmite o lote; respostas de sucesso do canal promovem `ChannelPublicationItem.status = SUCCEEDED`, o que avança `ChannelCatalogOffer.published_version = desired_version`; falhas individuais movem o item para `FAILED` com `error_code`, mantendo `published_version` na versão anterior.

3. **Critérios de Isolamento Técnico de S13.2:**
   - Separar expressamente correções técnicas de publicação (payload, idempotência, timeouts) de decisões de repasse financeiro, ATP (Available-to-Promise) e comissões do canal, que pertencem à camada comercial do Commerce OS;
   - **Nenhum código novo de S13.2 deve ser escrito** antes da aprovação formal deste diagnóstico e fechamento dos portões pendentes.
