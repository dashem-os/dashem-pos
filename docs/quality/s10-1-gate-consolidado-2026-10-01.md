# S10.1 — Gate Interno Consolidado do Channel Hub

Data de consolidação: 01 de outubro de 2026  
Commit de referência: `4b5e312` (publicado em `main`, CI 36861234960)  
Decisão do Gate: **S10.1 CONCLUÍDO NO GATE INTERNO FUNDACIONAL**  
Fundamentação: Todos os requisitos fundacionais (R1–R20) e critérios de retenção/privacidade da etapa fundacional (P1–P11 e P17–P21) estão plenamente comprovados com testes automatizados e evidências auditadas. As proteções financeiras e contratuais de D1/R11 estão aprovadas e publicadas. A travessia autenticada R20 foi validada com limites e responsabilidades estritamente delimitados.

Conforme previsto na proposta original (§7, itens 7 a 9), a conclusão deste gate interno mantém expressas as seguintes pendências operacionais e etapas posteriores:
1. **Retenção sem purga física:** P12–P16 pertencem à etapa posterior de purga (§7, item 9), a ser desenvolvida após a formalização do ciclo de backups (G2).
2. **D2 operacional pendente:** Cancelamento com item em preparo permanece retido no comportamento conservador comprovado (`NEEDS_REVIEW` com código `PREPARATION_STARTED`), preservando produção e cobertura financeira; a esteira de resolução humana é apresentada como proposta operacional para decisão do lojista.
3. **Avisos automáticos D8 pendentes:** Nenhuma emissão automática de aviso ao canal está habilitada; avisos continuam restritos ao acionamento explícito enquanto a matriz de transições D8 aguarda definição de vocabulário e canal piloto.
4. **Acesso a dados de contato condicionado à D7:** As 4 permissões especiais existem no catálogo sem concessão a perfis padrão; a leitura de dados de contato segue bloqueada até definição explícita de perfis.
5. **Canais comerciais não homologados:** A fundação foi provada contra o adaptador de referência (`CONTRACT_TEST`); homologação com marketplaces reais (iFood, 99Food, Rappi) depende de etapas comerciais e credenciamento técnico externos.

---

## 1. Separação de Evidências de Publicação

1. **Repositório Git e Integração Contínua (CI):**
   - Commit: [`4b5e312`](https://github.com/dashem-os/dashem-pos/commit/4b5e312e72b7fbbd189e6cbc64f569d035c21b1d) em `main`.
   - CI GitHub Actions: [Run 36861234960](https://github.com/dashem-os/dashem-pos/actions/runs/36861234960) verde nos 4 jobs (Alembic 54s, Backend tests 3m44s, Frontend typecheck/build 25s, Operational access E2E 1m21s).
2. **Deploy Frontend (Vercel):**
   - Deployment `6784097052` associado ao commit `4b5e312` com estado `success`.
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
| **R19** | Controle negativo: idempotência por linha quebrada de propósito — R2 tem de ver a duplicata / vazamento (medida). | `test_channel_inbox.py:273` (`test_r19_controle_idempotencia_por_linha_quebrada_de_proposito_enxerga_duplicata`) | `PASSED` | Commit prematuro plantado na primeira linha deixa pedido e item órfãos no banco de dados; a asserção detecta o vazamento, provando a eficácia do controle de R2. |
| **R20** | Travessia autenticada completa na interface com gestora e leitora (H8, H11). | [`hom09_canais_de_venda.cjs`](file:///D:/Workplace/Dashem%20POS/frontend/e2e/presentation/hom09_canais_de_venda.cjs), [`hom09-canais.json`](evidence/s10-1-2026-10-01/hom09-canais.json) | `PASSED` | 17 etapas, 10 telas capturadas, 0 falhas; gestora opera e leitora recebe HTTP 403 estrito. Aferição visual e ações operacionais no navegador; garantias de catálogo e finanças demonstradas no backend. |

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
| **P8** | Ingestão de pedido de canal não cria nem altera cliente de CRM, fidelidade ou dado fiscal (H19). | `test_channel_inbox.py:500` (`test_a_pessoa_mora_so_no_contato_e_evento_sem_pedido_nao_cria_contato`) | `PASSED` | Ingestão externa não insere registros na tabela `customers` nem muta cadastros fiscais. Não impede associação manual posterior no PDV. |
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

A travessia autenticada R20 (`hom09_canais_de_venda.cjs`) foi executada com sucesso contra o ambiente integrado local:
- **Valores enviados pelo roteiro:** Produto `CHOPE-500` com preço unitário de `R$ 18,50`, quantidade `2`, taxa de entrega de `R$ 7,00`, total de `R$ 44,00` e pagamento `PAID_ONLINE`.
- **Valores verificados pela API:** A consulta `GET /api/v1/orders/{order_id}` atesta que o pedido foi criado com `items[0].unit_price == "18.5000"` e `items[0].quantity == "2.0000"`.
- **Garantias demonstradas pelos testes backend:** A preservação do acervo em `ProductPrice` (R$ 18,00), a divergência no mapeamento (`difference_amount == Decimal("1.0000")`), a composição de `_order_amount()` e o bloqueio de cobrança local (`409 ORDER_PAID_IN_MARKETPLACE`) foram comprovados pelos testes backend automatizados de R11 (`test_channel_inbox.py` e `test_r11_concurrency_matrix.py`) e **não são atribuídos ao navegador**.
- **Autenticação:** Sessão iniciada com JWT de teste assinado localmente com `AUTH_TEST_SECRET`, contra API em `AUTH_MODE=test` e concessões no PostgreSQL isolado. Não comprova login interativo com formulário de usuário/senha nem a infraestrutura do Supabase Auth em produção.
- **Responsividade:** A varredura nas larguras 1366 px, 1024 px, 768 px e 390 px afere estritamente a ausência de palavras partidas ao meio (`palavrasPartidas`), sem afirmar ausência universal de defeitos de layout.

---

## 4. Desenho Preliminar de D2 (Proposta Operacional Revisada)

Esta seção formaliza a proposta de avanço para a decisão operacional **D2** (Cancelamento pelo canal com item já em preparo na cozinha), sem introduzir comportamentos automáticos perigosos nem violar as garantias de R11.

### A. Diagnóstico da Realidade Operacional e do Canal
1. **Notificação Definitiva vs. Solicitação Negociável:**
   - Em certos adaptadores/marketplaces (ex.: iFood em determinadas etapas), o evento `ORDER_CANCELLED` constitui uma **notificação unilateral e definitiva**: o cancelamento já foi consumado na plataforma externa, o cliente não receberá a refeição e não haverá repasse financeiro do canal. Nesses casos, uma "recusa de cancelamento" local no PDV **não desfaz o cancelamento externo**. O lojista deve decidir internamente se interrompe a produção para estancar o consumo de insumos ou se descarta o item, tratando a perda através dos canais de disputa/reembolso com o marketplace.
   - Em outros fluxos, o canal envia uma **solicitação de cancelamento** (`CANCELLATION_REQUESTED`), na qual o restaurante tem uma janela de tempo para aceitar ou recusar formalmente a solicitação antes que ela se torne definitiva.
2. **Assincronia do Estorno Financeiro:**
   - Uma transação relacional no PostgreSQL atualiza atômica e localmente as entidades do sistema (`Order`, `ProductionTicket`, `PaymentAllocation`), mas **não executa nem torna atômico um estorno externo** junto a adquirentes de cartão, gateways de pagamento ou plataformas de marketplace.
   - Qualquer operação financeira deve separar três fases assíncronas:
     - *Fase 1 (Resolução Local):* Registro da decisão humana e bloqueio de novas cobranças;
     - *Fase 2 (Solicitação Externa):* Emissão do comando de estorno/cancelamento para a adquirente ou canal;
     - *Fase 3 (Confirmação Financeira):* Recepção da confirmação externa (via webhook ou polling) antes de marcar a liquidação como estornada.
3. **Preservação Estrita das Proteções Financeiras de R11:**
   - A resolução humana jamais pode liberar reservas ou registrar estornos sem a devida confirmação. Em negociações vinculadas a múltiplos pedidos com cobertura conjunta (`coverage_on_orders`), o cancelamento de um pedido não pode reduzir a cobertura global abaixo da obrigação restante dos demais pedidos.
   - Todo caminho resolutivo que alcance entidades financeiras deve obedecer à **ordem canônica de bloqueios completa de R11**:
     $$\text{PaymentIntent (N1)} \rightarrow \text{CheckoutNegotiation (N2)} \rightarrow \text{TableSession (N3)} \rightarrow \text{ServiceTable (N4)} \rightarrow \text{Order (N5)} \rightarrow \text{ExternalOrderMapping (N6)} \rightarrow \text{OrderItem (N7)}$$
4. **Estados Reais do Modelo de Dados:**
   - O estado terminal de cancelamento em `ProductionTicket` é **`CANCELED`** (`DISCARDED` não existe no enum `ProductionTicketStatusEnum`).
   - Os estados válidos de `ChannelInboxEvent` são `RECEIVED`, `PROCESSING`, `APPLIED`, `SUPERSEDED`, `QUARANTINED`, `NEEDS_REVIEW`, `DISCARDED` e `EXPIRED`.
   - Se o lojista aceitar o cancelamento do pedido, o evento de cancelamento da caixa de entrada transiciona para **`APPLIED`** (aplicando o cancelamento ao `Order` e ao `ProductionTicket`); se o lojista mantiver o pedido aberto (rejeitando a solicitação ou tratando o evento como perda interna sem cancelar o pedido no PDV), o evento transiciona para **`DISCARDED`** com motivo justificado. Estados novos como `RESOLVED_CANCELED` ou `RESOLVED_REJECTED` exigiriam migração de schema e só devem ser introduzidos se houver benefício comprovado em auditoria.
5. **Autoria e Não Obrigatoriedade de PIN / Segunda Pessoa:**
   - Em operações enxutas de pequenos estabelecimentos, o mesmo operador acumula funções de salão, caixa e gerência. Portanto, a resolução de cancelamentos **não deve impor obrigatoriamente PIN de supervisor ou segunda pessoa**. A exigência central é a autorização formal (permissão `channel.manage` ou permissão específica delegada) e o registro auditado de autoria (`actor_id`, `resolved_at` e justificativa) em `audit_events`.
6. **Comunicação Outbound e Incerteza de Rede:**
   - O envio de confirmações ou recusas para o canal depende da declaração da capacidade `ChannelCapability.ORDER_STATUS_OUTBOUND`.
   - O enfileiramento na tabela `channel_outbound_messages` garante persistência local, mas **não garante entrega imediata**. Falhas de rede ou indisponibilidade do canal movem a mensagem para `RETRY` ou `DEAD_LETTER`, mantendo o status de comunicação em estado explícito de incerteza até confirmação definitiva.

### B. Proposta das Duas Alternativas Operacionais de Resolução

```
                         [ ORDER_CANCELLED recebido pelo conector ]
                                             │
                                (Item já aceito na cozinha?)
                                             │ SIM
                                             ▼
                                 [ NEEDS_REVIEW gravado ]
                            (Código: PREPARATION_STARTED)
                         (Order e ProductionTicket seguem OPEN)
                                             │
                   ┌─────────────────────────┴─────────────────────────┐
                   ▼                                                   ▼
     [ Alternativa A: Aceitar Cancelamento ]             [ Alternativa B: Rejeitar Cancelamento ]
     • Indicada para solicitação negociável ou           • Indicada para pedido já finalizado/embalado
       quando a cozinha consegue parar a tempo.            ou quando o lojista decide entregar/disputar.
     • Ação autorizada com justificativa auditada.       • Ação autorizada com justificativa auditada.
     • ProductionTicket -> CANCELED                      • ProductionTicket -> segue OPEN (ou READY)
     • Order no PDV -> CANCELED                          • Order no PDV -> segue OPEN
     • Desfaz reserva não liquidada / solicita estorno   • Cobertura financeira local mantida
     • Evento na inbox -> APPLIED                        • Evento na inbox -> DISCARDED
     • Se canal suportar outbound -> envia aviso         • Se canal suportar outbound -> envia aviso
```

**Recomendação Técnica:** Manter o comportamento conservador atual na fundação. A implementação da esteira interativa (diálogo com as Alternativas A e B) deve ocorrer na fatia de experiência operacional de atendimento/delivery, mantendo a regra de que o sistema **nunca cancela produção nem desfaz financeiro de forma automática e desatendida**.

---

## 5. Matriz de Avisos Outbound ao Canal (D8)

Para estruturar a futura decisão **D8** (quais transições do pedido geram avisos automáticos ao canal) sem ativar emissões precipitadas, define-se a seguinte matriz de comportamento:

| Evento Local do Ciclo de Vida | Mensagem Outbound | Condição de Enfileiramento | Prevenção de Eco (Anti-Echo) |
|---|---|---|---|
| Ticket aceito na cozinha (`ACCEPTED`) | `ORDER_ACCEPTED` | Canal declara `ORDER_STATUS_OUTBOUND` | Não aplicável (evento local). |
| Ticket pronto para entrega (`READY`) | `ORDER_PREPARED` | Canal declara `ORDER_STATUS_OUTBOUND` | Não aplicável (evento local). |
| Despacho com entregador (`DISPATCHED`) | `ORDER_DISPATCHED` | Canal declara `ORDER_STATUS_OUTBOUND` | Não aplicável (evento local). |
| Pedido cancelado no PDV (`CANCELED`) | `ORDER_CANCELLED` | Canal declara `ORDER_STATUS_OUTBOUND` | **ESTRITA:** Se a transição para `CANCELED` tiver sido provocada por um webhook de entrada originado do próprio canal (`ORDER_CANCELLED`), o emissor outbound **nunca** gera aviso de cancelamento para o canal, prevenindo loops de eco. |

- **Idempotência Outbound:** Chave determinística gerada a partir de `connection_id:order_id:message_type:version`, garantindo que reenvios ou retentativas não dupliquem notificações no marketplace.
- **Situação Atual:** Nenhuma emissão automática está ativada no código de produção. Os avisos continuam a ser despachados exclusivamente via endpoint explícito (`POST /api/v1/channels/orders/{id}/outbound`).

---

## 6. Proposta de Concessões por Perfil (D7)

As quatro permissões criadas na migração 098 encontram-se cadastradas na tabela `permissions` sem atribuição a nenhum perfil padrão (conforme comprovado em P20). Para habilitar operações de piloto com canal sem violar o princípio de menor privilégio, propõe-se a seguinte matriz de concessões:

| Permissão | Finalidade Operacional | Perfil Recomendado | Justificativa e Salvaguardas |
|---|---|---|---|
| `channel.order_contact.read` | Visualizar nome, telefone e endereço para expedição e entrega. | **Operador de Delivery / Expedição** (`ORDER_DISPATCHER` ou concessão nominal) | Restrita à janela operacional do pedido (até o estado terminal). Não concedida a perfis de garçom ou atendente de balcão. Toda leitura gera registro nominal em `audit_events`. |
| `channel.legal_hold.manage` | Aplicar ou liberar `legal_hold` sobre eventos, evidências ou contatos em disputa judicial. | **Gerente de Loja / Administrador** (`STORE_MANAGER`, `TENANT_ADMIN`) | Exige fornecimento obrigatório dos 5 campos estruturados (motivo, processo, responsável, revisão). Não delegável a operadores comuns. |
| `channel.retention.extend` | Estender prazo de retenção de registro além da política padrão por necessidade administrativa. | **Administrador do Tenant** (`TENANT_ADMIN`) | Ação excepcional. Requer motivo em código e prazo delimitado. Auditada. |
| `channel.retention.purge` | Disparar manualmente a rotina de limpeza física de registros vencidos. | **Administrador da Plataforma / Suporte Especializado** (`PLATFORM_SUPPORT`, `TENANT_ADMIN`) | Ação destrutiva definitiva. Não disponível no PDV diário. Exige registro de contagens de linhas expurgadas em `audit_events`. |

---

## 7. Preparação para a Próxima Fatia: Transição para S13.2

Com o gate interno fundacional do S10.1 concluído, o projeto prepara a transição para o épico **S13.2 (Catálogo e Integrações Avançadas)**, iniciando pelo **executor de publicação de catálogo por versão**:

1. **Diagnóstico do Código Existente:**
   - O contrato em `app/modules/channels/contracts.py` já declara a capacidade `ChannelCapability.CATALOG_PUBLICATION`;
   - O conector de referência (`reference.py`) implementa as assinaturas de contrato básicas, mas ainda não possui rotina de carga e sincronização diferencial de produtos/categorias;
   - As tabelas `channel_catalog_mappings` associam entidades locais (`PRODUCT`, `MODIFIER`) a identificadores externos, mas não rastreiam versão publicada nem hash de catálogo.
2. **Escopo Mínimo de S13.2 (Fatia 1):**
   - Criação de snapshot versionado do catálogo de delivery da loja (`CatalogPublicationRevision`);
   - Mapeamento determinístico de itens com preço, complementos e disponibilidade;
   - Executor assíncrono de publicação utilizando o conector de referência;
   - Tratamento de idempotência e retentativas: cada tentativa de publicação leva `publication_version` como chave; respostas atrasadas ou falhas parciais são tratadas sem duplicação de itens.
3. **Critérios de Isolamento Técnico:**
   - Separar expressamente correções técnicas de publicação (payload, idempotência, timeouts) de decisões de repasse financeiro, ATP (Available-to-Promise) e comissões do canal, que pertencem à camada comercial do Commerce OS.
