# Proposta — S10.1: completar a fundação do Channel Hub

Status: **proposta para revisão do dono · nada implementado** · revisão 1 em
16/09/2026.
Base: `6ab9066` em `main`, CI verde. Escopo e gate vêm do
[roadmap](roadmap-commerce-os-v2.md) (S10.1) e das
[fundações do Channel Hub](channel-hub-fundacoes-2026-09-10.md).

Não escolhe canal, provedor, preço, plano nem capability produtiva. Não trata
de catálogo, disponibilidade e repasses: isso é o S13.2, que vem depois e se
apoia no contrato definido aqui. Nada nesta proposta autoriza dizer que iFood,
99Food ou qualquer canal está conectado.

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
| **C9** | O payload bruto, com nome do cliente, fica guardado sem prazo | `ChannelInboxEvent.raw_payload` | Política de dados pessoais indefinida, como as fundações já apontavam |
| **C10** | O formulário pede ao lojista uma "referência segura das credenciais" (`secret://...`); a caixa de entrada mostra códigos em inglês e UUID; mensagens de saída não aparecem | `ChannelHubWorkspace.tsx` | Contraria "o lojista não preenche referência de cofre"; falha não fica visível para quem opera |

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
| `models.py`, `api.py` | tabelas novas e rotas |

`channel_hub_service` migra para o módulo por partes; o comportamento público
muda apenas onde esta proposta diz.

### 3.2 Contrato por capacidades

O adaptador declara o que sabe fazer. Não existe adaptador obrigado a tudo.

| Capacidade | O que cobre | Entra em |
|---|---|---|
| `CONNECTION_VALIDATION` | confirmar merchant e autorização do estabelecimento | S10.1 |
| `ORDER_INGRESS` | verificar assinatura, extrair eventos, normalizar pedido | S10.1 |
| `ORDER_EVENTS` | atualização, cancelamento e ordem dos eventos do mesmo pedido | S10.1 |
| `ORDER_STATUS_OUTBOUND` | avisar o canal (aceito, pronto, despachado, cancelado) | S10.1 |
| `CATALOG_PUBLICATION` | publicar ofertas por versão | S13.2 |
| `AVAILABILITY` | disponibilidade desejada e confirmada | S13.2 |
| `SETTLEMENT_IMPORT` | documentos de repasse | S13.2 |

Tipos normalizados, independentes de canal:

- **evento**: identificador do evento no canal, tipo (`ORDER_PLACED`,
  `ORDER_UPDATED`, `ORDER_CANCELLED`), pedido externo, **chave de ordem**
  declarada pelo adaptador (sequência do canal ou instante do evento) e o pedido
  normalizado quando houver;
- **pedido**: identificador externo, forma de atendimento, linhas, taxa de
  entrega, desconto e subsídio do canal, total declarado e origem do pagamento;
- **linha**: identificador da linha no canal, **código do item no canal**,
  quantidade, valor unitário e desconto declarados, complementos por código do
  canal e observação.

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
  sem dado pessoal.
- A rota antiga `POST /channels/webhooks`, que só os testes usam, sai (D5).

### 3.4 Caixa de entrada retomável

Estados do evento:

| Estado | Significa |
|---|---|
| `RECEIVED` | persistido e confirmado ao canal; ainda não aplicado |
| `PROCESSING` | reivindicado com lease; lease vencido volta a `RECEIVED` |
| `APPLIED` | efeito no pedido concluído |
| `SUPERSEDED` | mais antigo que o já aplicado, ou chegou depois do cancelamento; registrado, não aplicado (H5) |
| `QUARANTINED` | não aplicável sem intervenção, com motivo nomeado — item sem mapeamento, pedido inválido; retomável depois de corrigida a causa |
| `NEEDS_REVIEW` | exige pessoa: cancelamento com item em preparo, divergência de conteúdo no mesmo evento (H6) |

`DUPLICATE` deixa de ser estado de linha: o mesmo evento não gera linha nova, e
evento novo sobre o mesmo pedido é atualização.

Aplicação, com cada passo idempotente pela identidade externa:

1. **Pedido.** `Order`, linhas e `ExternalOrderMapping` na **mesma transação**.
   Hoje `create_order` e `add_item` confirmam sozinhos; `operation` passa a
   oferecer a abertura de pedido externo como uma unidade de trabalho, com chaves
   derivadas de conexão + pedido externo e conexão + pedido + linha externa. Se
   ainda assim algo parar no meio, a retomada completa sem duplicar (H2, H3).
2. **Atualização.** Diferença por linha externa: linha nova entra, quantidade
   muda, linha removida é cancelada — enquanto o item não entrou em preparo.
   Item já em preparo não é alterado por evento: vira `NEEDS_REVIEW`.
3. **Cancelamento.** Operação nova no Order Engine (C8), com autoria do
   principal da conexão. Pedido sem item em preparo é cancelado; com item em
   preparo, `NEEDS_REVIEW` e aviso na tela (D2).
4. **Ordem.** O mapeamento guarda a última chave de ordem aplicada; evento com
   chave anterior vira `SUPERSEDED`. Cancelamento é terminal para atualizações.

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

### 3.7 Dados pessoais e autoridade

- Payload bruto com prazo de retenção; depois dele, fica só o normalizado sem
  dado pessoal. Nome, telefone e endereço ficam só enquanto a entrega precisar.
  Prazos são decisão sua (D3).
- `channel.configure` para conexões e `channel.manage` para retomar e reenviar,
  ambas já existentes. Numa operação de uma pessoa só, essa pessoa tem as duas;
  nenhuma ação exige uma segunda pessoa.

### 3.8 Interface

Operação → Canais de venda, reusando o `ChannelHubWorkspace`:

- conexão mostra estado **por capacidade** e última sincronização;
- a caixa de entrada fala a língua da operação — "Aplicado", "Aguardando código
  do item X no canal", "Cancelado pelo canal com item em preparo" — e mostra o
  pedido pelo número, não pelo UUID; detalhe técnico fica no detalhe;
- nova seção "Avisos ao canal", com falhas e "Reenviar";
- o campo `secret://` sai do formulário do lojista (H12).

Entregue quando percorrido na tela, e não quando o teste passar.

### 3.9 Migração

Uma migração nova para os estados e colunas da caixa de entrada, a tabela de
linhas externas, a chave de ordem e os valores no mapeamento, e as colunas do
executor, com RLS igual à das tabelas do S10. Ela sobe junto com o código que a
exercita, nunca antes: `main` migra produção a cada push.

## 4. Dependências de cada canal

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
| **E8** | Termos sobre dados do cliente | retenção calibrada | retenção mínima por padrão |

## 5. O que muda para quem opera

Nada, enquanto não houver canal real: o conector de referência só existe em teste
e desenvolvimento. Quando houver, o pedido do canal passa a sobreviver a queda no
meio, a aceitar atualização e cancelamento, a preservar o valor cobrado e a dizer
na tela o que está parado e por quê.

## 6. Matriz de testes

**Real nestas provas:** banco, concorrência, reinício entre passos, HTTP até a
API, lease e retomada. **Simulado, e declarado:** todo comportamento do canal —
assinatura, eventos, respostas aos avisos e indisponibilidade.

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
| R9 | Atualização depois do cancelamento: registrada, não aplicada | H5, H6 |
| R10 | Item sem mapeamento: quarentena nomeada; depois do mapeamento, "Retomar" aplica | H2, H11 |
| R11 | Valores do canal preservados; diferença com a oferta registrada | H7 |
| R12 | Aviso entregue só com confirmação; transitório → `RETRY`; esgotado → `DEAD_LETTER`; "Reenviar" autorizado | H8 |
| R13 | Tempo esgotado no aviso: repetição com a mesma chave, ou consulta antes | H8 |
| R14 | Canal indisponível durante avisos: venda local no PDV segue, medida contra baseline | H10 |
| R15 | Ingresso de merchant do tenant A não alcança o tenant B; corpo com tenant alheio é ignorado | H9 |
| R16 | Assinatura sobre bytes: mesmo conteúdo reserializado não passa | H9 |
| R17 | Merchant sem conexão autorizada: recusado sem dado pessoal gravado | H9, H12 |
| R18 | Capacidade não declarada não é chamada e aparece como ausente | H11 |
| R19 | Controle: idempotência por linha quebrada de propósito — R2 tem de ver a duplicata | medida |
| R20 | Travessia na tela: evento aplicado, em quarentena, em revisão e aviso em `DEAD_LETTER` | H8, H11 |

## 7. Ordem de implementação, depois do aceite

1. Módulo, contrato por capacidades e conector de referência, sem mudar
   comportamento.
2. Migração e ingresso por provedor com conexão resolvida no servidor; sai a rota
   antiga (R15–R17).
3. Caixa de entrada retomável e abertura de pedido externo como unidade de
   trabalho (R1–R5, R10, R19).
4. Atualização, ordem e cancelamento, com a operação nova no Order Engine
   (R6–R9).
5. Valores do canal, depois de D1 (R11).
6. Executor de avisos (R12–R14, R18).
7. Tela e travessia (R20).
8. Gate do S10.1: todos os R, com os limites escritos.

Os passos 1 a 4 não dependem de nenhuma decisão abaixo.

## 8. Decisões que dependem de você

| # | Decisão | Recomendação |
|---|---|---|
| **D1** | Preço do item de pedido externo | Valor declarado pelo canal, com a diferença para a oferta registrada |
| **D2** | Cancelamento do canal com item já em preparo | Pendência para pessoa; a produção não é cancelada sozinha |
| **D3** | Retenção do payload bruto e dos dados do cliente | Prazo curto para o bruto; dado de contato só enquanto a entrega durar — números seus |
| **D4** | Recuperação sem worker hospedado no Render free | Aceitar os gatilhos (a), (c) e (d) até o gate de pré-piloto financiar o worker, com o limite dito na tela |
| **D5** | Rota antiga `/channels/webhooks` | Remover; só os testes a usam |

Fora do alcance desta proposta, e não perguntado aqui: escolha do primeiro canal,
contratação, preços, planos e o S13.2.
