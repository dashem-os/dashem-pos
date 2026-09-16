# Proposta — S10.1: completar a fundação do Channel Hub

Status: **passos 1 a 4 autorizados pelo dono · D3 aprovada como política técnica
inicial · D6 e D7 decididas · retenção não implementada até a purga e o controle
de backups serem comprovados** · revisão 3 em 16/09/2026 (revisões 1 e 2 em
16/09/2026).
Base: `b90aeba` em `main`. Cabeça de migração conferida no código e no banco local
nesta revisão: `097_the_pinpad_is_occupied`, sem nenhuma posterior. Escopo e gate
vêm do [roadmap](roadmap-commerce-os-v2.md) (S10.1) e das
[fundações do Channel Hub](channel-hub-fundacoes-2026-09-10.md).

Não escolhe canal, provedor, preço, plano nem capability produtiva. Não trata
de catálogo, disponibilidade e repasses: isso é o S13.2, que vem depois e se
apoia no contrato definido aqui. Nada nesta proposta autoriza dizer que iFood,
99Food ou qualquer canal está conectado.

## 0.1 O que mudou da revisão 2 para a 3

| # | Revisão 2 dizia | Revisão 3 |
|---|---|---|
| 1 | D3 "decidida" | **Aprovada** pelo dono como política técnica inicial; continua sem valor jurídico nem comercial |
| 2 | Evento que nunca vira pedido ficava "sem âncora" até D6 | **D6 decidida:** nenhum evento fica sem âncora. O payload conta da recepção, a quarentena não reinicia o relógio, e evento nunca processado expira (§3.7.4) |
| 3 | D7 pedia quem recebe as ações, sem permissões | **D7 decidida:** quatro permissões separadas por ação, acesso mínimo e auditoria, uma pessoa pode acumular. Criadas no catálogo **sem concessão**, e as rotas ficam bloqueadas até concessão definida e testada (§3.7.8) |
| 4 | Uma migração para tudo | **Uma migração por passo**, cada uma com o código que a exercita (§3.9) |
| 5 | — | O contato só é extraído quando o evento é aplicado a um pedido. Evento que nunca vira pedido não gera linha de contato: o dado pessoal sai com o payload, dentro do teto da D6 |
| 6 | — | `retention_basis` registra de onde veio cada prazo; um prazo atribuído só encurta — alongar exige hold ou extensão autorizada |
| 7 | — | Estados `EXPIRED` e `DISCARDED` na caixa de entrada |

## 0. O que mudou da revisão 1 para a 2

| # | Revisão 1 dizia | Revisão 2 |
|---|---|---|
| 1 | D3: "prazo curto para o bruto; números seus" | **Decidida** como política técnica inicial com prazos definidos pelo dono (§3.7.1), sujeita a validação jurídica e de privacidade, sem valor de conformidade legal nem de promessa comercial |
| 2 | Dados pessoais tratados numa frase | **Três camadas** separadas — payload bruto, dados operacionais pessoais e evidência normalizada —, cada uma com armazenamento, prazo e destino próprios (§3.7.2) |
| 3 | Sem estrutura de retenção | `retention_until`, campos de legal hold e marcas de purga definidos por tabela (§3.7.3); a migração só nasce com o código que a exercita (§3.9) |
| 4 | Sem achados de dado pessoal além do payload | Cinco achados novos: nome copiado para `orders.notes`, motivo de quarentena com texto de exceção, trilhas imutáveis, ausência de permissão de privacidade e **pedido de canal sem estado terminal** (C11–C15) |
| 5 | Purga não descrita | Contrato de purga futura para armazenamento primário, caches, réplicas, backups e logs; purga efetiva fica para etapa posterior (§3.7.6) |
| 6 | — | **Guarda contra log com dado pessoal implementado** em `backend/tests/test_no_personal_data_in_logs.py` (§3.7.7) |
| 7 | — | Lacunas de autoridade registradas sem fluxo inventado (§3.7.8); CRM, fidelidade e fiscal seguem finalidade própria (§3.7.9) |

## 1. O que a leitura do código encontrou

O S10 passou no gate interno com um adaptador de contrato. Lido com olhos de
conector real, o caminho tem defeitos concretos — não só lacunas de plano.
Nenhum é risco em produção hoje: fora de teste e desenvolvimento só existe o
adaptador indisponível, e nenhum canal real envia eventos.

| # | Achado | Onde | Consequência |
|---|---|---|---|
| **C1** | O pedido é processado dentro da requisição do webhook, com commits separados: pedido, cada item e mapeamento | `channel_hub_service.receive_event`; `order_service.create_order` e `add_item` confirmam por conta própria | Queda no meio deixa evento em `NORMALIZED` e pedido parcial. Reenviar o mesmo evento devolve o registro sem retomar ([linha 194](../../backend/app/services/channel_hub_service.py#L194)) |
| **C2** | A chave de idempotência do item usa o id do **evento** | [linha 257](../../backend/app/services/channel_hub_service.py#L257) | Depois de uma queda, um segundo evento do mesmo pedido **duplica os itens** |
| **C3** | Todo evento de pedido já mapeado vira `DUPLICATE` | [linha 219](../../backend/app/services/channel_hub_service.py#L219) | Atualização e **cancelamento vindos do canal são descartados** |
| **C4** | `queue_outbound` grava `PENDING`; nada leva a `DELIVERED`, `RETRY` ou `DEAD_LETTER` | `queue_outbound` | Aviso ao canal nunca sai, e a tela não mostra |
| **C5** | O contrato do adaptador tem só `validate_connection` e `normalize`; o item normalizado chega com o **UUID interno** do produto | [channel_adapter.py](../../backend/app/providers/channel_adapter.py) | Canal real manda o código dele; o mapeamento do S13 (`ChannelCatalogMapping`) não participa da entrada |
| **C6** | O item recebe o **preço local** (`ProductPrice`) | `order_service.add_item`, linhas 303–318 | Preço, desconto, taxa de entrega e subsídio do canal se perdem; o total do pedido pode não ser o que o cliente pagou |
| **C7** | Tenant, unidade e conexão vêm do **corpo** do webhook; o segredo é derivado de `SECRET_KEY` + chave de idempotência e recalculado a cada verificação — o hash guardado não é usado; a assinatura é conferida sobre o JSON **reserializado**, não sobre os bytes recebidos | `ChannelWebhookDTO`, `_webhook_secret`, `_verify_signature` | O mesmo padrão do A5 do TEF; trocar `SECRET_KEY` quebra todos os webhooks; nenhum canal real assina JSON reserializado |
| **C8** | O Order Engine não tem operação de cancelar pedido: nenhum serviço leva `Order` a `CANCELED` | `order_service` | Cancelamento do canal não tem destino canônico |
| **C9** | O payload bruto, com nome do cliente, fica guardado sem prazo | `ChannelInboxEvent.raw_payload` | Sem retenção, sem purga, sem legal hold |
| **C10** | O formulário pede ao lojista uma "referência segura das credenciais" (`secret://...`); a caixa de entrada mostra códigos em inglês e UUID; mensagens de saída não aparecem | `ChannelHubWorkspace.tsx` | Contraria "o lojista não preenche referência de cofre"; falha não fica visível para quem opera |
| **C11** | O nome do cliente é **copiado** para as observações do pedido: `notes = "Cliente: {nome}"` | [linha 251](../../backend/app/services/channel_hub_service.py#L251) | Dado pessoal fora da camada que terá prazo: purgar o evento não alcançaria `orders.notes` |
| **C12** | O motivo de quarentena guarda o texto da exceção | [linha 288](../../backend/app/services/channel_hub_service.py#L288) | Adaptador cuja mensagem de erro traga trecho do payload grava dado pessoal num campo sem prazo |
| **C13** | `audit_events` e `published_events` são **imutáveis** — gatilho recusa `UPDATE`/`DELETE` e o papel da aplicação não tem essas permissões (migrações `044` e `066`); `queue_outbound` põe na outbox o `payload` recebido de quem chamou, e a outbox vira `published_events` | `reliability`; [linha 328](../../backend/app/services/channel_hub_service.py#L328) | Dado pessoal que entrar numa trilha imutável **nunca mais pode ser purgado** |
| **C14** | Não existe permissão nem capability para ler dado pessoal de canal, registrar legal hold, estender retenção ou executar limpeza | migrações e `app/modules/capabilities` | Nada disso pode ser oferecido sem antes ser decidido (§3.7.8) |
| **C15** | Pedido de canal pago no marketplace **nunca fica terminal**: o Order Engine só fecha pedido pela finalização do pagamento ou pelo fechamento de mesa, e não cancela | `negotiation_service` (linha 1607), `table_service` (linha 887) | Sem estado terminal, nenhum prazo que parte dele começa a contar |

Conferido também, sem defeito: em 16/09/2026 as dez chamadas de log e `print` do
backend registram só identificadores e contagens, e o middleware não registra
corpo de requisição. O log de acesso do servidor tem endereço de origem da
conexão, método, caminho e status — nenhuma rota de canal leva dado pessoal no
caminho, mas o endereço de origem entra no teto de 14 dias do provedor (G3).

## 2. Invariantes

Tudo abaixo existe para sustentar estas afirmações. Cada teste da seção 6 se liga
a pelo menos uma.

| # | Invariante |
|---|---|
| **H1** | Nada do canal é processado antes de persistido; a confirmação HTTP sai depois do commit do evento |
| **H2** | Processar é retomável: a mesma função, chamada de novo sobre o mesmo evento, termina o trabalho sem repetir efeito, qualquer que seja o ponto em que parou |
| **H3** | Um pedido externo produz exatamente um `Order`; cada linha é identificada pela **linha externa**, nunca pelo evento que a trouxe |
| **H4** | Duplicata é o **mesmo** evento. Evento novo sobre pedido existente é atualização classificada — nunca descartada em silêncio |
| **H5** | Evento mais antigo que o já aplicado não faz o pedido regredir: fica registrado como superado |
| **H6** | Cancelamento do canal tem destino no Order Engine; cancelamento de pedido com item já em preparo vira pendência visível, não apagamento |
| **H7** | Valor declarado pelo canal é fato do canal e fica preservado; diferença com o preço publicado é registrada, não corrigida por suposição |
| **H8** | `PENDING` não é entrega: aviso ao canal só é `DELIVERED` com confirmação do adaptador; falha esgotada fica visível com ação autorizada |
| **H9** | Tenant, unidade e conexão saem do servidor, nunca do corpo da requisição |
| **H10** | Indisponibilidade do canal nunca bloqueia venda local: nada no caminho do PDV chama o canal |
| **H11** | Capacidade não declarada pelo adaptador não é chamada; a ausência aparece como estado explícito |
| **H12** | Credencial de canal não é digitada pelo lojista; autorização do estabelecimento é separada de elegibilidade comercial |
| **H13** | Payload bruto, dados operacionais pessoais e evidência normalizada são **camadas separadas**, cada uma com seu prazo; nome, telefone, endereço e instruções de entrega moram **num único lugar** |
| **H14** | **Nenhum registro fica sem âncora.** O payload de evento aplicado conta do **estado terminal** do pedido; o de evento em quarentena, descartado ou nunca processado conta da **recepção**. Corrigir a causa de uma quarentena não reinicia o relógio. Um prazo atribuído só encurta; alongar exige legal hold ou extensão autorizada |
| **H15** | Purgar remove conteúdo e preserva hash, identificadores, instantes, resultado, versão do parser e trilha mínima; purgar é idempotente e decidido pelos campos de retenção, então reaplicar depois de um restore remove de novo o que voltou |
| **H16** | Legal hold suspende a purga **só da camada e do registro marcados**, e só com motivo, referência, responsável e data de revisão; hold vencido não segura nada |
| **H17** | Payload bruto e dado pessoal **nunca** entram em log nem em trilha imutável (`audit_events`, `outbox_events` → `published_events`, eventos de transação e de execução); motivo de quarentena é código mais texto seguro |
| **H18** | Ler contato, registrar ou liberar legal hold, estender retenção e executar limpeza exigem **cada uma a sua permissão** (D7) e capability; enquanto a concessão não estiver definida e testada, **nenhuma rota oferece essas ações** |
| **H19** | CRM, fidelidade, emissão fiscal e conta própria do estabelecimento seguem a finalidade deles; o pedido de canal não os alimenta nem empresta seu prazo |
| **H20** | Limpeza sem executor contínuo é limitação declarada: registro vencido aguardando limpeza aparece na documentação e na tela |

## 3. Desenho

### 3.1 Módulo `app/modules/channels/`

Nasce no módulo (ADR-029 §1.2), como o transporte TEF nasceu em
`app/modules/finance/bridge/`. `channels` pode usar `operation`, `catalog`,
`identity` e `shared`; nunca `finance`.

| Arquivo | Responsabilidade |
|---|---|
| `contracts.py` | capacidades, protocolos e tipos normalizados (§3.2) |
| `registry.py` | adaptador por `provider_code`; o de referência só em teste e desenvolvimento |
| `adapters/reference.py` | conector de referência que implementa todas as capacidades com provedor simulado; sucede o `ContractTestChannelAdapter` |
| `ingress.py` | autenticação por provedor, resolução da conexão no servidor, persistência e confirmação |
| `inbox.py` | processamento retomável, reivindicação com lease e gatilhos |
| `orders.py` | aplicação ao Order Engine pelas operações de `operation` |
| `outbound.py` | executor de avisos ao canal |
| `retention.py` | âncora terminal, cálculo de prazo e o contrato da purga futura (§3.7) |
| `models.py`, `api.py` | tabelas novas e rotas |

`channel_hub_service` migra para o módulo por partes; o comportamento público
muda apenas onde esta proposta diz.

### 3.2 Contrato por capacidades

O adaptador declara o que sabe fazer. Não existe adaptador obrigado a tudo.

| Capacidade | O que cobre | Entra em |
|---|---|---|
| `CONNECTION_VALIDATION` | confirmar merchant e autorização do estabelecimento | S10.1 |
| `ORDER_INGRESS` | verificar assinatura, extrair eventos, normalizar pedido | S10.1 |
| `ORDER_EVENTS` | atualização, conclusão, cancelamento e ordem dos eventos do mesmo pedido | S10.1 |
| `ORDER_STATUS_OUTBOUND` | avisar o canal (aceito, pronto, despachado, cancelado) | S10.1 |
| `CATALOG_PUBLICATION` | publicar ofertas por versão | S13.2 |
| `AVAILABILITY` | disponibilidade desejada e confirmada | S13.2 |
| `SETTLEMENT_IMPORT` | documentos de repasse | S13.2 |

Tipos normalizados, independentes de canal:

- **evento**: identificador do evento no canal, tipo (`ORDER_PLACED`,
  `ORDER_UPDATED`, `ORDER_CONCLUDED`, `ORDER_CANCELLED`), pedido externo,
  **chave de ordem** declarada pelo adaptador (sequência do canal ou instante do
  evento), **versão do parser** que o normalizou e o pedido normalizado quando
  houver;
- **pedido**: identificador externo, forma de atendimento, linhas, taxa de
  entrega, desconto e subsídio do canal, total declarado e origem do pagamento;
- **contato** — separado do pedido de propósito (H13): nome de exibição,
  telefone, endereço de entrega e instruções de entrega, quando o canal os
  enviar;
- **linha**: identificador da linha no canal, **código do item no canal**,
  quantidade, valor unitário e desconto declarados, complementos por código do
  canal e observação de preparo.

O código do item no canal é resolvido para produto pelo `ChannelCatalogMapping`
do S13. Item sem mapeamento põe o evento em quarentena com motivo nomeado, e,
feito o mapeamento, o mesmo evento é retomado (H2) — sem pedir ao canal que
reenvie.

### 3.3 Ingresso

- **Uma rota por provedor**, `POST /channels/ingress/{provider_code}`, a URL
  que se cadastra no portal do canal. O adaptador verifica a assinatura sobre os
  **bytes recebidos**, no esquema que a documentação do canal definir, e extrai
  os eventos com o identificador do merchant. A conexão é resolvida no servidor
  por provedor e merchant (H9).
- **Segredo do lado do servidor.** O material de verificação vem da credencial
  do aplicativo na plataforma, nunca do lojista e nunca do banco em claro. O
  conector de referência usa segredo por conexão só para os testes. A derivação
  atual a partir de `SECRET_KEY` sai.
- **Persistir antes de confirmar** (H1), um registro por evento, com restrição
  única por conexão e evento. Mesmo evento repetido → confirma e não cria nada
  (H4). Mesmo identificador com conteúdo diferente → confirma, registra a
  divergência e não aplica: recusar faria o canal reenviar para sempre. O código
  de resposta exato depende da semântica de reenvio de cada canal (E3).
- **Merchant sem conexão autorizada** → recusado com registro técnico mínimo,
  sem dado pessoal e sem payload.
- A rota antiga `POST /channels/webhooks`, que só os testes usam, sai (D5).

### 3.4 Caixa de entrada retomável

Estados do evento:

| Estado | Significa |
|---|---|
| `RECEIVED` | persistido e confirmado ao canal; ainda não aplicado |
| `PROCESSING` | reivindicado com lease; lease vencido volta a `RECEIVED` |
| `APPLIED` | efeito no pedido concluído |
| `SUPERSEDED` | mais antigo que o já aplicado, ou chegou depois do estado terminal; registrado, não aplicado (H5) |
| `QUARANTINED` | não aplicável sem intervenção, com **código** de motivo e texto seguro (H17) — item sem mapeamento, pedido inválido; retomável depois de corrigida a causa |
| `NEEDS_REVIEW` | exige pessoa: cancelamento com item em preparo, divergência de conteúdo no mesmo evento (H6) |
| `DISCARDED` | classificado como não aplicável por ação autorizada (`channel.manage`); definitivo |
| `EXPIRED` | o prazo do payload venceu antes de o evento ser aplicado; sem payload não há retomada; definitivo |

`DUPLICATE` deixa de ser estado de linha: o mesmo evento não gera linha nova, e
evento novo sobre o mesmo pedido é atualização.

Aplicação, com cada passo idempotente pela identidade externa:

1. **Pedido.** `Order`, linhas, `ExternalOrderMapping` e contato na **mesma
   transação**. Hoje `create_order` e `add_item` confirmam sozinhos; `operation`
   passa a oferecer a abertura de pedido externo como uma unidade de trabalho,
   com chaves derivadas de conexão + pedido externo e conexão + pedido + linha
   externa. O contato vai para a sua camada, e **não** para `orders.notes` (C11).
   Se ainda assim algo parar no meio, a retomada completa sem duplicar (H2, H3).
2. **Atualização.** Diferença por linha externa: linha nova entra, quantidade
   muda, linha removida é cancelada — enquanto o item não entrou em preparo.
   Item já em preparo não é alterado por evento: vira `NEEDS_REVIEW`.
3. **Conclusão e cancelamento — o estado terminal (C8, C15).** Duas operações
   novas no Order Engine para pedido de origem externa, com autoria do principal
   da conexão: concluir e cancelar. Conclusão chega por evento do canal ou por
   ação autorizada no PDV quando o canal não informar. Pedido sem item em preparo
   é cancelado; com item em preparo, `NEEDS_REVIEW` e aviso na tela (D2). O
   instante em que o pedido fica terminal é gravado no mapeamento e é a âncora
   dos prazos (H14).
4. **Ordem.** O mapeamento guarda a última chave de ordem aplicada; evento com
   chave anterior vira `SUPERSEDED`. Estado terminal encerra as atualizações.

**Gatilhos, e o limite do Render free.** A mesma função atende três chamadas:
(a) logo depois da confirmação, na mesma instância, como tarefa após a resposta;
(b) varredura com lease pelo worker; (c) botão "Retomar" na tela, com
`channel.manage`. Mais um gatilho oportunista: (d) todo evento novo de uma
conexão retoma os pendentes daquela conexão. No Render free não há worker
hospedado (ADR-027), então (b) só roda localmente: um evento que parar sem
tráfego seguinte espera (c). Isso fica dito na tela e no gate, não escondido
(D4).

### 3.5 Valores do canal

Por linha, guarda o valor unitário e o desconto declarados. Por pedido, guarda
taxa de entrega, desconto, subsídio e total declarados, numa tabela de linhas
externas e em colunas do mapeamento. O preço que o `OrderItem` carrega é decisão
sua (D1). A recomendação é o valor declarado pelo canal, que é o que o cliente
pagou, com a diferença para a oferta publicada registrada (H7). Pagamento online
do canal continua origem `MARKETPLACE`, distinto de TEF e de repasse.

### 3.6 Executor de avisos ao canal

- `ChannelOutboundMessage` é a fila própria, como o ADR-027 manda: "cada
  adaptador externo terá seu próprio registro de entrega". Reivindicação com
  `SKIP LOCKED` e lease; ganha lease, instante de entrega, referência do canal e
  código do último erro.
- Adaptador confirma → `DELIVERED` (H8). Erro transitório → `RETRY` com espera
  crescente. Erro permanente ou tentativas esgotadas → `DEAD_LETTER`, visível,
  com "Reenviar" sob `channel.manage`.
- **Tempo esgotado sem resposta não é falha nem sucesso.** A repetição reenvia
  com a mesma chave de idempotência, se o canal oferecer (E4); se não oferecer,
  consulta o estado do pedido no canal antes de reenviar (E5).
- **Quem gera os avisos.** Os eventos que o Order Engine já publica na fila
  interna, para pedidos com origem externa. O conjunto inicial se limita às
  transições que já existem; aviso sem transição correspondente não é inventado.
- **O aviso não carrega dado pessoal para a outbox** (C13, H17): a outbox leva
  identificadores; o conteúdo que o canal precisar é montado pelo executor na
  hora do envio, a partir das camadas com prazo.

### 3.7 Dados de canais: retenção, legal hold e autoridade (D3)

#### 3.7.1 Política técnica inicial

Aprovada pelo dono em 16/09/2026 como política técnica inicial.

> **Isto não é orientação jurídica.** Os prazos abaixo são uma **política técnica
> inicial** para construir e testar a fundação. Antes de virar política externa,
> termo de uso, cláusula contratual ou argumento comercial, precisam ser validados
> pelo responsável jurídico e de privacidade. Esta proposta não declara
> conformidade com a LGPD nem com qualquer norma.

| Dado | Prazo | Depois do prazo |
|---|---|---|
| **Payload bruto** do canal | até **30 dias** após o pedido atingir estado terminal | o conteúdo é removido; ficam hash, identificadores, instantes, resultado, versão do parser e trilha mínima de processamento |
| **Nome, telefone e endereço** (e instruções de entrega) | até **90 dias** após o estado terminal | eliminados, redigidos ou substituídos por identificador pseudonimizado |
| **Logs com dado pessoal acidental** | no máximo **14 dias** | expiram no provedor de logs; **novos logs não registram payload bruto, telefone ou endereço** |
| **Evidência normalizada** da transação | pelo prazo legal, fiscal, regulatório ou de auditoria aplicável, **somente com finalidade documentada** | segue a finalidade; isso **não** autoriza guardar payload bruto ou dado pessoal operacional por cinco anos automaticamente |
| **Disputa ou incidente** | `LEGAL_HOLD` só para os dados necessários ao caso | com motivo, responsável, referência e revisão; vencido, o prazo normal volta a valer |

**Estado terminal** é o pedido `CLOSED` (concluído ou entregue) ou `CANCELED` no
Order Engine, ou a conclusão ou o cancelamento declarados pelo canal — o que for
gravado primeiro. Hoje nenhum pedido de canal chega lá (C15); o passo 3 de §3.4
dá esse caminho.

#### 3.7.2 Três camadas

| Camada | Onde mora | Contém | Não contém | Prazo |
|---|---|---|---|---|
| **Payload bruto** | `channel_inbox_events` | o corpo recebido do canal, como chegou | — | 30 dias após o terminal, ou após a recepção quando o evento não foi aplicado sem quarentena (§3.7.4) |
| **Dados operacionais pessoais** | `channel_order_contacts`, nova, 1:1 com o pedido externo | nome de exibição, telefone, endereço, instruções de entrega e o pseudônimo | valores, itens, identificadores de conciliação | 90 dias após o terminal |
| **Evidência normalizada** | `external_order_mappings`, `external_order_lines` (nova) e a trilha da caixa de entrada | identificadores externos, instantes, valores declarados, estados, resultado, hash do payload, versão do parser | nome, telefone, endereço, instruções, payload | pela finalidade documentada |

Ficam fora das três, e por isso nunca recebem dado pessoal ou payload: logs,
`audit_events`, `outbox_events`, `published_events`, eventos de transação e de
execução, `orders.notes`, `idempotency_records` e o motivo de quarentena (H17).

A observação de **preparo** de cada linha ("sem cebola") segue para o item do
pedido e para a produção, porque é instrução de cozinha. Texto livre pode trazer
dado pessoal por acidente, e esse texto não é alcançado pela redação do contato —
limite declarado, não resolvido aqui.

#### 3.7.3 Estrutura de dados

Definida aqui e criada por partes, cada parte na migração do passo que a exercita (§3.9).

**`channel_inbox_events`** — payload bruto, colunas novas:

| Coluna | Tipo | Regra |
|---|---|---|
| `raw_payload` | passa a aceitar nulo | nulo só depois da purga |
| `parser_version` | texto curto | versão do adaptador que normalizou |
| `retention_basis` | `RECEPCAO` · `ESTADO_TERMINAL` | de onde veio o prazo (§3.7.4) |
| `retention_until` | instante, nulo | recepção + 30 dias ao persistir; terminal + 30 dias quando a base passa a `ESTADO_TERMINAL`; nulo só enquanto um evento aplicado aguarda o terminal |
| `purged_at` | instante, nulo | quando o conteúdo saiu |
| campos de legal hold | ver abaixo | |

Continuam depois da purga: `id`, `provider_event_id`, `external_order_id`,
`event_type`, `payload_hash`, estado, código de quarentena, `received_at`,
`acknowledged_at`, `processed_at`, `parser_version` e a trilha de tentativas.

**`channel_order_contacts`** — dados operacionais pessoais, tabela nova, RLS por
tenant e unidade como as do S10:

| Coluna | Tipo | Regra |
|---|---|---|
| `external_order_mapping_id` | referência única | um contato por pedido externo; só existe quando um evento é **aplicado** a um pedido |
| `display_name`, `phone`, `delivery_address`, `delivery_instructions` | texto e estrutura, nulos | o que o canal enviou e a entrega precisa |
| `pseudonym` | texto curto | gerado ao criar a linha, aleatório, sem derivar do conteúdo; é o que resta depois |
| `retention_basis` | `ESTADO_TERMINAL` · `CLASSIFICACAO_DEFINITIVA` | de onde veio o prazo |
| `retention_until` | instante, nulo | terminal + 90 dias; nulo enquanto o pedido não fica terminal |
| `redacted_at` | instante, nulo | quando o conteúdo saiu |
| `redaction_method` | `ERASED` · `REDACTED` · `PSEUDONYMIZED` | como saiu |
| campos de legal hold | ver abaixo | |

**`external_order_mappings`** — evidência, colunas novas: `terminal_state`,
`terminal_at` (a âncora), a chave de ordem aplicada e os valores declarados
(§3.5), `evidence_purpose` — código de uma finalidade documentada, nulo enquanto
não houver — e `retention_until`, só preenchido quando houver finalidade. Sem base, a
evidência não ganha prazo estendido e aparece como "finalidade não documentada";
ela não tem dado pessoal por construção (H13).

**Campos de legal hold**, iguais nas três tabelas, para que o hold alcance só a
camada e o registro necessários (H16):

| Coluna | Regra |
|---|---|
| `legal_hold_until` | fim do hold; nulo = sem hold |
| `legal_hold_reason` | motivo, **sem dado pessoal** |
| `legal_hold_reference` | processo, incidente ou protocolo |
| `legal_hold_by` | responsável |
| `legal_hold_review_at` | próxima revisão, obrigatória |

Uma restrição de banco exige os cinco juntos ou nenhum. O histórico de quem
registrou, estendeu ou liberou vai para `audit_events` com identificadores e
datas, sem motivo em texto livre e sem dado pessoal. Isso não é uma plataforma de
governança: são colunas e uma regra.

#### 3.7.4 Âncora e prazo (D3 e D6)

Nenhum registro fica sem âncora (H14). D6, decidida pelo dono em 16/09/2026,
fecha o caso que a política do pedido terminal não cobria.

| Situação do evento | Prazo do payload bruto | Contato |
|---|---|---|
| Persistido, ainda não aplicado | **recepção + 30 dias** (`RECEPCAO`), gravado na mesma transação que persiste | não existe linha de contato |
| Aplicado a um pedido **sem nunca ter passado por quarentena** | a base passa a `ESTADO_TERMINAL`: nulo até o terminal, depois **terminal + 30 dias** | criado na aplicação; **terminal + 90 dias** |
| Em quarentena — inclusive por falta de mapeamento | continua **recepção + 30 dias**; o relógio não para | não existe linha de contato |
| Saiu da quarentena e foi aplicado | continua **recepção + 30 dias**: corrigir o cadastro não cria retenção nova | criado na aplicação; terminal + 90 dias |
| Descartado (`DISCARDED`) ou expirado sem aplicação (`EXPIRED`) | recepção + 30 dias; é esse vencimento que torna `EXPIRED` definitivo | não existe linha de contato |
| Chega depois do terminal, ou superado | o do pedido: terminal + 30 dias | o do pedido |

Regras que atravessam a tabela:

- **Um prazo atribuído só encurta.** A única troca para mais tarde é a de
  `RECEPCAO` para `ESTADO_TERMINAL`, uma vez, para o evento aplicado sem
  quarentena — é o caso que a D3 cobre. Qualquer outro alongamento exige legal
  hold ou extensão autorizada (§3.7.8).
- **O contato só nasce da aplicação.** Evento que nunca vira pedido não gera
  linha de contato: nome, telefone e endereço ficam só dentro do payload e saem
  com ele, em no máximo 30 dias da recepção — dentro do teto de 90 dias que a D6
  dá ao contato a partir da classificação definitiva. Se um dia for preciso
  extrair o contato antes da aplicação, por exemplo para revisar uma quarentena,
  vale a regra da D6: a partir da classificação definitiva, com base
  `CLASSIFICACAO_DEFINITIVA`, em no máximo 90 dias.
- **Evento sem dado pessoal** segue a mesma regra do payload. Depois da purga
  ficam só os metadados técnicos mínimos (§3.7.3).
- **Pedido aplicado que nunca fica terminal** mantém o prazo aguardando o
  terminal, e aparece na tela com a idade. É um problema de operação, porque o
  pedido ficou aberto, e não uma âncora ausente. Nenhum prazo é inventado para
  ele aqui.

#### 3.7.5 O que a purga faz, quando existir

Elegível quando `retention_until <= agora` **e** não há hold vigente
(`legal_hold_until` nulo ou vencido).

- Payload: `raw_payload` vira nulo, `purged_at` é gravado.
- Contato: nome, telefone, endereço e instruções saem; fica o pseudônimo;
  `redacted_at` e `redaction_method` são gravados.
- Evidência: nada, até existir base documentada com prazo.
- Uma linha em `audit_events` por lote, com contagens e identificadores.
- A elegibilidade é decidida pelos campos de retenção, não por `purged_at`: a
  varredura é idempotente e, rodada depois de um restore, remove de novo o que o
  backup trouxe de volta (H15).

#### 3.7.6 Contrato para a purga futura

| Onde o dado pode estar | Como a purga o alcança | Situação hoje |
|---|---|---|
| **Armazenamento primário** (Postgres do Supabase) | varredura em lote por `retention_until` | contrato definido; varredura não implementada |
| **Caches** | respostas `/api` saem com `no-store`; não há cache de servidor para estas tabelas; a tela mantém dados só em memória | nada a purgar hoje; cache novo precisa respeitar `retention_until` |
| **Réplicas** | réplica gerenciada recebe a remoção pela replicação | nenhuma réplica hoje; réplica fora do provedor exigiria a mesma varredura |
| **Backups** | backup não é reescrito; o dado some quando o backup sai do ciclo de expiração do provedor; restore é seguido da varredura | **ciclo não documentado** (G2) — até documentar, "removido" vale só para o armazenamento primário |
| **Logs** | não escrever (§3.7.7); o que escapar expira no provedor | **retenção do provedor não conferida** (G3) |

**Sem worker contínuo, a limpeza não é automática.** No Render free (ADR-027) a
varredura pode rodar por: (i) worker hospedado, quando houver; (ii) execução
local; (iii) gatilho oportunista, em lote pequeno, junto de outra operação do
tenant; (iv) ação autorizada na tela, com `channel.retention.purge` — que
existe no catálogo sem concessão até ser definida e testada (§3.7.8). A documentação e a tela dizem quantos registros estão vencidos
aguardando limpeza e quando foi a última (H20).

Fora desta fase: serviço externo de descarte, certificado de eliminação,
inventário geral de dados pessoais e fluxo de atendimento a titular.

#### 3.7.7 Logs — implementado

`backend/tests/test_no_personal_data_in_logs.py` lê pela árvore sintática toda
chamada a logger, `logging`, `print` e `warnings.warn` do backend e reprova a que
receber payload, corpo, telefone, endereço, CEP, cliente ou contato — como
variável, atributo, chave de acesso, chave de dicionário ou expressão de f-string.
Um controle planta seis vazamentos e três chamadas seguras, uma delas em arquivo
com BOM, e exige o conjunto exato.

**Limite:** mensagem de exceção que carregue dado, registrada como `exc` ou por
`logger.exception`, passa pelo guarda. Por isso o motivo de quarentena vira
código (H17, P9), e o teto de 14 dias existe para o que escapar.

#### 3.7.8 Autoridade (D7)

Decidida pelo dono em 16/09/2026: uma permissão por ação, acesso mínimo e
auditoria. `channel.manage` sozinha não cobre isto, porque são ações diferentes.

| Ação | Permissão | Quem, pela recomendação do dono |
|---|---|---|
| Ver nome, telefone e endereço para preparar e entregar | `channel.order_contact.read` | operador do canal, só quando precisa para executar o pedido |
| Registrar ou liberar `LEGAL_HOLD` | `channel.legal_hold.manage` | responsável pela unidade |
| Estender retenção além do prazo padrão | `channel.retention.extend` | responsável pela unidade |
| Executar ou solicitar limpeza | `channel.retention.purge` | administrador do tenant |
| Ver evidência normalizada, sem dado pessoal | `channel.read` ou `channel.manage` — já existem | quem já consulta o Channel Hub |

- **Uma pessoa pode acumular.** Numa operação de uma pessoa só, o mesmo usuário
  com as permissões executa tudo; nenhuma ação exige segunda pessoa.
- **Suporte e plataforma** entram por acesso excepcional, auditado e nominal —
  o acesso assistido que já existe —, e nunca aparecem como operador comum.
- **Toda leitura de contato e todo ato de hold, extensão ou limpeza** grava
  `audit_events` com quem, quando e sobre qual registro, sem o conteúdo.

**O que existe agora e o que fica bloqueado.** As quatro permissões novas entram
no catálogo na migração do passo 2, **sem concessão a nenhum perfil**. As rotas
de leitura de contato, hold, extensão e limpeza **não existem** até a concessão
ser definida e testada, e um teste garante que nenhum perfil as recebe antes
disso (P20). A capability de tenant que as habilite segue a mesma regra.
Consequência deliberada, e dita: com um canal real, a operação não veria o
endereço de entrega até a concessão estar pronta. Isso não afeta nada hoje, mas
**precisa estar pronto antes de qualquer piloto com canal**.

#### 3.7.9 Finalidades separadas

Cadastro de cliente para CRM ou fidelidade, dado fiscal da nota e a conta própria
do estabelecimento com o cliente seguem a finalidade e o prazo deles. A entrada
de um pedido de canal não cria nem atualiza esses cadastros com o contato do
canal, e o prazo do pedido de canal não se aplica a eles (H19). Se um dia o
estabelecimento quiser trazer esse cliente para o próprio cadastro, é um ato com
finalidade própria, fora deste escopo.

### 3.8 Interface

Operação → Canais de venda, reusando o `ChannelHubWorkspace`:

- conexão mostra estado **por capacidade** e última sincronização;
- a caixa de entrada fala a língua da operação — "Aplicado", "Aguardando código
  do item X no canal", "Cancelado pelo canal com item em preparo" — e mostra o
  pedido pelo número, não pelo UUID; detalhe técnico fica no detalhe;
- nova seção "Avisos ao canal", com falhas e "Reenviar";
- o campo `secret://` sai do formulário do lojista (H12);
- **retenção visível:** pedidos aguardando estado terminal, com a idade, e
  registros vencidos aguardando limpeza, com a data da última limpeza e a frase de que sem
  worker hospedado a limpeza não é automática (H20);
- nenhum nome, telefone ou endereço na tela sem `channel.order_contact.read`
  concedida e testada (H18).

Entregue quando percorrido na tela, e não quando o teste passar.

### 3.9 Migração

**Uma migração por passo**, cada uma com o código que a exercita, nunca antes:
`main` migra produção a cada push. RLS igual à das tabelas do S10.

| Passo | Migração |
|---|---|
| 2 | colunas de retenção, hold e `parser_version` da caixa de entrada; as quatro permissões no catálogo, sem concessão |
| 3 | estados e lease da caixa de entrada; tabela de contato; tabela de linhas externas |
| 4 | âncora terminal, chave de ordem aplicada e campos de evidência no mapeamento |
| 6 | colunas do executor de avisos |

A cabeça é conferida no código e no banco na criação de cada uma. Em 16/09/2026,
nesta revisão, era `097_the_pinpad_is_occupied`.

## 4. Dependências

### 4.1 De cada canal

O que esta fundação não garante sozinha. Cada item precisa ser conferido na
documentação do canal escolhido; a ausência não é defeito nosso, mas muda o que
se pode prometer.

| # | Dependência | Se existir | Se não existir |
|---|---|---|---|
| **E1** | Esquema de assinatura e origem do segredo | ingresso autentica o canal | ingresso restrito por outro meio acordado, ou não habilita |
| **E2** | Tipos de evento e chave de ordem | H5 aplicável | ordem só por instante de recebimento, com limite declarado |
| **E3** | Semântica de reenvio e prazo de confirmação | resposta calibrada | risco de reenvio contínuo ou evento perdido |
| **E4** | Idempotência nos avisos ao canal | repetição segura | repetição só depois de consulta (E5) |
| **E5** | Consulta de estado do pedido no canal | reconciliação automática | pendência para pessoa |
| **E6** | Regras de cancelamento e multas | H6 com prazos reais | cancelamento vira sempre revisão |
| **E7** | Modelo de códigos de item e complementos | mapeamento do S13 cobre | quarentena por item até mapear |
| **E8** | Termos do canal sobre dados do cliente | comparados com §3.7.1 | vale §3.7.1; **conflito entre os termos e a política vai ao jurídico**, não se ajusta sozinho |
| **E9** | Evento de conclusão do pedido | âncora terminal automática | conclusão por ação autorizada no PDV |

### 4.2 Fora do canal

| # | Dependência | De quem | Enquanto não houver |
|---|---|---|---|
| **G1** | Validação jurídica e de privacidade de §3.7.1 | responsável jurídico/privacidade | política técnica interna; nenhuma comunicação externa com os prazos |
| **G2** | Ciclo de expiração de backups do Supabase no plano vigente, documentado | dono, com o provedor | purga vale só para o armazenamento primário, e isso é dito |
| **G3** | Retenção de logs do Render e do Supabase no plano vigente, conferida contra os 14 dias | dono, com os provedores | o teto de 14 dias fica sem prova; o guarda impede escrita nova |
| **G4** | Worker hospedado | gate de pré-piloto (ADR-027) | limpeza por execução local, gatilho oportunista ou ação autorizada (§3.7.6) |
| **G5** | Finalidades documentadas para a evidência normalizada | jurídico/privacidade | evidência sem prazo estendido, marcada "finalidade não documentada" |

## 5. O que muda para quem opera

Nada, enquanto não houver canal real: o conector de referência só existe em teste
e desenvolvimento. Quando houver, o pedido do canal passa a sobreviver a queda no
meio, a aceitar atualização, conclusão e cancelamento, a preservar o valor
cobrado e a dizer na tela o que está parado e por quê — e o dado do cliente passa
a ter lugar único e prazo.

## 6. Matriz de testes

**Real nestas provas:** banco, concorrência, reinício entre passos, HTTP até a
API, lease e retomada. **Simulado, e declarado:** todo comportamento do canal —
assinatura, eventos, respostas aos avisos e indisponibilidade.

### 6.1 Pedido, caixa de entrada e avisos

| # | Teste | Garante |
|---|---|---|
| R1 | Dois consumidores reivindicam o mesmo evento: um aplica, o outro não repete | H2 |
| R2 | Parada depois de criar o pedido e antes das linhas: retomada completa sem duplicar | H2, H3 |
| R3 | Parada depois das linhas e antes de gravar a chave de ordem: retomada sem duplicar | H2, H3 |
| R4 | Canal reenvia o mesmo evento por confirmação perdida: nenhuma linha nova, nenhum efeito | H1, H4 |
| R5 | Mesmo identificador com conteúdo diferente: divergência registrada, nada aplicado | H4 |
| R6 | Atualização com linha nova, alterada e removida, aplicada por linha externa | H3, H4 |
| R7 | Atualização mais antiga que a aplicada: `SUPERSEDED`, pedido intacto | H5 |
| R8 | Cancelamento de pedido sem preparo cancela; com item em preparo, `NEEDS_REVIEW` visível | H6 |
| R9 | Atualização depois do estado terminal: registrada, não aplicada | H5, H6 |
| R10 | Item sem mapeamento: quarentena nomeada; depois do mapeamento, "Retomar" aplica | H2, H11 |
| R11 | Valores do canal preservados; diferença com a oferta registrada | H7 |
| R12 | Aviso entregue só com confirmação; transitório → `RETRY`; esgotado → `DEAD_LETTER`; "Reenviar" autorizado | H8 |
| R13 | Tempo esgotado no aviso: repetição com a mesma chave, ou consulta antes | H8 |
| R14 | Canal indisponível durante avisos: venda local no PDV segue, medida contra baseline | H10 |
| R15 | Ingresso de merchant do tenant A não alcança o tenant B; corpo com tenant alheio é ignorado | H9 |
| R16 | Assinatura sobre bytes: mesmo conteúdo reserializado não passa | H9 |
| R17 | Merchant sem conexão autorizada: recusado sem dado pessoal nem payload gravado | H9, H12, H17 |
| R18 | Capacidade não declarada não é chamada e aparece como ausente | H11 |
| R19 | Controle: idempotência por linha quebrada de propósito — R2 tem de ver a duplicata | medida |
| R20 | Travessia na tela: evento aplicado, em quarentena, em revisão e aviso em `DEAD_LETTER` | H8, H11 |

### 6.2 Retenção e dados pessoais

| # | Teste | Garante | Quando |
|---|---|---|---|
| **P1** | Pedido de canal fica terminal (concluído, cancelado, ou declarado pelo canal): `terminal_at` gravado; `retention_until` do payload aplicado sem quarentena = terminal + 30 dias e do contato = terminal + 90 dias, na mesma transação. Antes disso, ambos nulos e contados como "aguardando estado terminal", com a idade | H14 | passo 4 |
| **P2** | D6: ao persistir, todo evento recebe `retention_until` = recepção + 30 dias com base `RECEPCAO`, na mesma transação; nenhum evento persiste sem prazo | H14 | passo 2 |
| **P3** | Marcadores de nome, telefone e endereço no payload aparecem **só** em `channel_inbox_events.raw_payload` e em `channel_order_contacts` — varredura em `orders`, `order_items`, `audit_events`, `outbox_events`, `published_events`, eventos de transação, `idempotency_records` e motivo de quarentena | H13, H17 | passo 3 |
| **P4** | Aviso ao canal para pedido com contato: a outbox e `published_events` levam só identificadores | H17 | passo 6 |
| **P5** | Nenhum DTO ou rota grava `retention_until`, campos de legal hold ou `redaction_method` — tentativa pelo corpo é ignorada ou recusada | H18 | passo 2 |
| **P6** | Nenhuma rota devolve nome, telefone ou endereço; nenhuma rota registra hold, estende retenção ou dispara limpeza | H18 | passos 2 e 7 |
| **P7** | Restrição de banco: hold com algum dos cinco campos faltando é recusado | H16 | passo 2 |
| **P8** | Ingestão de pedido de canal não cria nem altera cliente de CRM, fidelidade ou dado fiscal | H19 | passo 3 |
| **P9** | Payload com marcador que provoca erro de normalização: o motivo de quarentena tem código e texto seguro, sem o marcador | H17 | passo 3 |
| **P10** | Tela e diagnóstico mostram vencidos aguardando limpeza e a última limpeza; com zero execuções, dizem isso | H20 | passo 7 |
| **P11** | **Implementado.** Nenhuma chamada de log ou `print` do backend passa payload, corpo, telefone, endereço, CEP, cliente ou contato; controle com seis vazamentos plantados e três chamadas seguras | H17 | feito em 16/09/2026 |
| **P12** | Purga do payload: conteúdo sai; hash, identificadores, instantes, resultado, versão do parser e trilha ficam; segunda execução não muda nada | H15 | purga |
| **P13** | Redação do contato: conteúdo sai, pseudônimo fica, pedido e evidência continuam legíveis | H13, H15 | purga |
| **P14** | Hold vigente no contato impede a redação do contato e não impede a purga do payload do mesmo pedido; hold vencido não impede nada | H16 | purga |
| **P15** | Restore: linhas restauradas de antes da purga, com retenção vencida, são purgadas de novo na varredura seguinte | H15 | purga |
| **P16** | Controle: varredura com a condição de hold removida de propósito — P14 tem de reprovar | medida | purga |
| **P17** | D6: evento em quarentena por falta de mapeamento, mapeado e aplicado depois, mantém recepção + 30 dias; o contato criado na aplicação conta do terminal | H14 | passo 3 |
| **P18** | D6: evento nunca aplicado cujo prazo venceu vira `EXPIRED`, definitivo; "Retomar" não o alcança | H14 | passo 3 |
| **P19** | Prazo só encurta: nenhuma transição do fluxo alonga `retention_until`, exceto a troca única de `RECEPCAO` para `ESTADO_TERMINAL` de evento aplicado sem quarentena; controle alonga de propósito e o teste reprova | H14 | passos 3 e 4 |
| **P20** | D7: as quatro permissões existem no catálogo e **nenhum perfil** as recebe; nenhuma rota as exige nem as contorna; controle concede uma a um perfil de propósito e o teste reprova | H18 | passo 2 |
| **P21** | Evento que nunca vira pedido não cria linha de contato; nome, telefone e endereço dele existem só no payload | H13, H14 | passo 3 |

**Limites destes testes, ditos antes:**

- P11 é estático: não enxerga mensagem de exceção com dado dentro;
- P2, P17, P18 e P19 provam que o prazo é **atribuído**; que o conteúdo **sai**
  no prazo só P12–P15 provam, e eles dependem da purga, que não existe;
- P3 procura marcadores conhecidos; não prova ausência de dado pessoal em texto
  livre de observação de preparo;
- P15 simula restore dentro do banco de teste; não prova nada sobre o backup real
  do provedor (G2);
- nenhum teste verifica prazos de log do provedor (G3) nem validade jurídica dos
  prazos (G1);
- pseudônimo aleatório não se reverte pelo banco, mas pode ser correlacionado por
  quem guardar a relação fora dele — limite de desenho, não de teste.

## 7. Ordem de implementação

Passos 1 a 4 autorizados pelo dono em 16/09/2026.

0. **Feito em 16/09/2026:** guarda contra log com dado pessoal (P11).
1. Módulo, contrato por capacidades e conector de referência, sem mudar
   comportamento.
2. Ingresso por provedor com conexão resolvida no servidor; sai a rota antiga;
   migração com retenção, hold e versão do parser na caixa de entrada e as quatro
   permissões sem concessão (R15–R17, P2, P5–P7, P20).
3. Caixa de entrada retomável, abertura de pedido externo como unidade de
   trabalho, contato na sua camada, fim da cópia para `orders.notes` e motivo de
   quarentena como código (R1–R5, R10, R19, P3, P8, P9, P17, P18, P21).
4. Atualização, ordem, conclusão e cancelamento, com as operações novas no Order
   Engine e a âncora terminal (R6–R9, P1, P19). Cancelamento com item em preparo
   usa o comportamento conservador — `NEEDS_REVIEW`, a produção não é cancelada
   sozinha — até D2.
5. Valores do canal, depois de D1 (R11).
6. Executor de avisos (R12–R14, R18, P4).
7. Tela e travessia, com retenção visível e sem dado pessoal (R20, P6, P10).
8. Gate do S10.1: todos os R, P1–P11 e P17–P21, com os limites escritos e a purga
   declarada como **não implementada**.
9. **Etapa posterior:** varredura de purga (P12–P16), depois de G2, e rotas de
   contato, hold, extensão e limpeza depois de a concessão da D7 ser definida e
   testada. Sem as duas coisas, retenção não é declarada implementada.

## 8. Decisões

| # | Decisão | Situação |
|---|---|---|
| **D1** | Preço do item de pedido externo | Pendente. Recomendação: valor declarado pelo canal, com a diferença para a oferta registrada |
| **D2** | Cancelamento do canal com item já em preparo | Pendente. O passo 4 usa o comportamento conservador recomendado — pendência para pessoa, a produção não é cancelada sozinha — até a decisão |
| **D3** | Retenção do payload bruto e dos dados do cliente | **Aprovada em 16/09/2026** como política técnica inicial (§3.7.1), sujeita a G1; não é orientação jurídica, não declara conformidade e não é compromisso comercial |
| **D4** | Recuperação sem worker hospedado no Render free | Seguida na autorização dos passos 1 a 4, que manda não esperar worker: gatilhos (a), (c) e (d) de §3.4 e (ii)–(iv) de §3.7.6, com o limite dito na tela |
| **D5** | Rota antiga `/channels/webhooks` | Seguida na autorização dos passos 1 a 4: sai no passo 2; só os testes a usam |
| **D6** | Âncora para evento que nunca vira pedido | **Decidida em 16/09/2026** (§3.7.4): payload conta da recepção, até 30 dias; contato, se um dia for extraído antes da aplicação, conta da classificação definitiva, até 90 dias; quarentena não reinicia o relógio; ressalvado `LEGAL_HOLD` |
| **D7** | Quem pode ler contato, registrar e liberar legal hold, estender retenção e executar limpeza | **Decidida em 16/09/2026** (§3.7.8): quatro permissões por ação, acesso mínimo, auditoria, acúmulo permitido. **Concessão a perfis pendente**: definir e testar antes de abrir as rotas e antes de qualquer piloto com canal |

Fora do alcance desta proposta, e não perguntado aqui: escolha do primeiro canal,
contratação, preços, planos e o S13.2.
