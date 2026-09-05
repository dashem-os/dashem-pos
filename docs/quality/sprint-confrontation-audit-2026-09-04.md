# Auditoria de confronto — S8 a S13 e S17

Data: 4 de setembro de 2026
Método: confronto entre as entregas declaradas no roadmap e o que existe no
repositório — modelo, serviço, endpoint, teste e tela. Nenhum estado foi
inferido por intenção ou por memória de conversa.

Régua aplicada, a do próprio roadmap (seção 10, item 7):

> "implementado" significa UI + API + persistência + autorização + testes, não
> mockup.

Por essa régua, backend pronto sem tela **não é sprint entregue**. É a diferença
entre o que a auditoria encontrou e o que se supunha.

## Quadro

| Sprint | Modelos | Serviço | Endpoint | Testes | Tela | Estado apurado |
|---|---|---|---|---|---|---|
| S8 — Checkout Negotiation | 5 | sim | `/negotiations` | `test_s8_checkout_negotiation.py` | mesa e pagamento por comanda | **PARCIAL** |
| S9 — Providers e TEF Bridge | 7 | sim | `/providers` | `test_s9_payment_providers.py` | `PaymentProviderManager` (desde 05/09) | **entregue no gate interno** |
| S10 — Channel Hub | 4 | sim | `/channels` | `test_s10_channel_hub.py` | `ChannelHubWorkspace` | **entregue no gate interno** |
| S11 — Production e KDS | 6 | sim | `/production` | `test_s11_production_kds.py` | `KdsShell`, `DeviceManager`, `CatalogManager` | **entregue no gate interno** |
| S12 — Transferências | 1 + eventos | sim | `/transfers` | `test_s12_transfers.py` | item, comanda, sessão, mesclagem e linhagem | **entregue no gate interno** |
| S13 — Channel Catalog | 6 | sim | `/channel-catalog` | `test_s13_channel_catalog_reconciliation.py` | `ChannelHubWorkspace`, leitura e escrita (desde 05/09) | **entregue no gate interno** |
| S17 — BI V1 | 2 | sim | `/management` | `test_s17_business_intelligence.py` | `DashboardBI` | **entregue no gate interno** |

## Detalhe por sprint

### S8 — Checkout Negotiation e Payment Orchestrator · PARCIAL

`CheckoutNegotiation`, `NegotiationOrder`, `PaymentIntent`, `PaymentAllocation` e
`NegotiationEvent` existem, com pagamento parcial levando a sessão de mesa a
`PARTIALLY_PAID`. O cliente da API tem cinco chamadas.

Falta: a negociação só é consumida pelo fluxo de mesa
(`TableServiceWorkspace`). O fechamento de balcão continua no caminho antigo de
`Sale`, o que o roadmap previa como coexistência temporária ("o fluxo atual de
`Sale` continuará atendendo compatibilidade enquanto `CheckoutNegotiation` passa
a governar o fechamento"), mas a migração não foi concluída e não há data.

Também não é representável **dividir a conta por pessoa**: o parcial é por
valor, não por consumidor.

### S9 — Payment Providers e Dashem TEF Bridge · PARCIAL

O núcleo está construído: `PaymentProviderConfiguration`, `TefBridgeTerminal`,
`PaymentDeviceBinding`, `ProviderTransaction`, `ProviderTransactionEvent`,
`PaymentExecutionEvent` e `OperationalProductivityProjection`.

Falta o que mais se nota no uso: **não existe tela de cadastro**. Nenhum
componente consome `fetchProviderConfigurations`. Um lojista não tem como
cadastrar provider, terminal de bridge ou vínculo de maquininha pela interface —
só por API. Isso explica a percepção registrada em 04/09 de que a tela de
Terminais e dispositivos parece genérica: a metade do assunto que trata de
pagamento não está lá.

**Atualização de 05/09/2026 — a tela existe e o S9 sai de `PARCIAL`.**
`PaymentProviderManager` está montado no `ManagementLayout` sob o destino
`payment_providers`, guardado pela capability `tef` e pela permission
`provider.read`. Ele cadastra configuração de provider, pareia terminal de
bridge TEF, cria vínculo de maquininha e muda status de vínculo, e traz na
própria tela o aviso de que SmartPOS é somente cadastro enquanto não houver
adapter homologado. O achado que fechava esta auditoria — "fechar o Gate C sobre
uma funcionalidade que nenhum lojista consegue usar" — deixou de valer.

Registro de vocabulário, porque a confusão apareceu: **o S9 não é o cadastro de
produtos e sortimentos.** Aquilo é o S4, estendido pelo Gate 5.4.0 com a
atividade como propriedade do conjunto curado. O S9 é provider de pagamento,
bridge TEF e vínculo de dispositivo de cobrança.

**Correção de 04/09, mais tarde no mesmo dia.** A frase original dizia que não
havia teste dedicado ao Gate C nem aos negativos que ele exige. Isso era
**parcialmente falso**: `test_s9_payment_providers.py` já cobria três dos oito
critérios do ADR-022 — o 1 (payload legado escolhendo provider e terminal é
recusado com 422), o 4 (bridge offline não bloqueia dinheiro, PIX nem outra
parcela) e o 5 (SmartPOS recusado com 409 explícito). O que faltava de fato era
a **matriz de cruzamento**, critérios 2, 3 e 7, agora em
`tests/test_gate_c_payment_device_binding.py`.

### S10 — Dashem Channel Hub · entregue no gate interno

`MerchantConnection`, `ChannelInboxEvent`, `ExternalOrderMapping` e
`ChannelOutboundMessage`, com serviço, endpoint, teste e `ChannelHubWorkspace`
consumindo. O gate externo de certificação de canal permanece independente.

### S11 — Production Routing e KDS · entregue no gate interno

`ProductionPoint`, `ProductionRoutingRule`, `ProductionDispatch`,
`ProductionTicket`, `ProductionTicketItem` e `ProductionTransition`, com `/kds`
real e roteamento configurável no catálogo e nos dispositivos. O fallback de
impressão depende do Print Bridge, que continua no S21.1.

### S12 — Transferências e Comandas Avançadas · ENTREGUE NO GATE INTERNO

**Correção de registro.** Em 4/9/2026 este agente afirmou duas vezes que a
transferência de comanda não existia — primeiro que não estava no roadmap,
depois que estava planejada e não construída. As duas afirmações estavam
erradas e as linhas de dívida correspondentes foram corrigidas.

O que existe: `transfer_item` move item entre sessões com split de quantidade,
recusando item coberto por `PaymentAllocation` ou já materializado em venda, e
sinalizando compensação de produção. `merge_sessions` reatribui **todas** as
comandas da sessão de origem para a destino e encerra a origem, liberando a mesa
física. Como `TableSessionKindEnum.INDIVIDUAL_TAB` é uma sessão sem mesa, a
junção também é o caminho de "descer para o balcão". Tudo com `TransferRecord`
imutável, versão esperada, idempotência, evento por sessão, auditoria e outbox.

Atualização de fechamento em 04/09: os três pontos foram implementados. A
operação move `Order` inteira entre sessões, separa uma comanda diretamente para
mesa livre, muda uma sessão inteira de mesa e mescla sessões. A tela mostra os
comandos e a linhagem, e o checkout por Order permite pagar uma pessoa ou grupo
sem encerrar os demais.

**Segunda correção de registro, 04/09, no confronto com a auditoria do Codex.**
A frase original deste item dizia que "`mergeSessions` não é chamado por nenhum
componente". O mecanismo estava **errado**: não existe `mergeSessions` no
cliente da API. Naquele momento, das três rotas de `/transfers`, só
`POST /transfers/items` tinha chegado ao cliente. O fechamento posterior tornou
mesclagem e linhagem alcançáveis e acrescentou as operações que faltavam.

### S13 — Channel Catalog e Marketplace Reconciliation · PARCIAL

Seis modelos, serviço, endpoint e teste existem.

**Correção de 04/09, no confronto com a auditoria do Codex.** A frase original
dizia "nenhuma tela consome". Era **falsa**: `ChannelHubWorkspace` carrega
`fetchChannelCatalogState` e `fetchMarketplaceSettlements` na mesma chamada em
que busca conexões e inbox.

O que era verdade em 04/09 é mais específico e não melhor: a superfície era
**somente de leitura**. Das oito rotas de `/channel-catalog`, o cliente da API
expunha as duas `GET`. As seis de escrita — mapeamento por merchant, oferta,
lote de publicação, resultado item a item, repasse e pagamento de repasse — não
tinham função no cliente. O lojista via o estado da publicação e da conciliação,
e não podia publicar nem conciliar. Era uma janela sem maçaneta.

**Fechado em 05/09/2026.** Cinco das seis escritas chegaram à tela: oferta por
canal, vínculo do código do item, lote de publicação, importação do documento de
repasse e registro do pagamento. A projeção passou a resolver no servidor o nome
e o SKU do produto, o provider e o merchant da conexão, os itens de cada lote e
os pagamentos de cada documento — a tela deixou de exibir identificador e deixou
de precisar juntar listas no navegador.

A sexta escrita, `POST /publications/{batch_id}/results`, **continua sem botão
por desenho**. Ela é o adapter reportando o que o canal respondeu; oferecê-la a
uma pessoa seria deixá-la assinar a palavra do marketplace, e todo lote leria
verde sem o canal ter sido chamado. Enquanto não houver provider homologado, o
lote fica pendente e a tela diz isso. A mesma leitura vale para
`POST /channels/orders/{order_id}/outbound`, que é do worker. As duas
permanecem na linha de base de `test_surface_reachability.py`, agora com o
motivo escrito.

### S17 — Business Intelligence V1 · entregue no gate interno

`BiDailyFact` e `BiProjectionState` com `DashboardBI` consumindo. A tela foi
observada em produção em 04/09 mostrando estado vazio real, sem fixture.

## Achado transversal — a modularização foi iniciada e abandonada

O roadmap coloca entre suas obrigações "a obrigação de modularizar desde o
início, sem microserviços prematuros", e a seção 4.2 declara que "os limites
modulares passam a valer imediatamente".

O que existe: `app/modules/` contém **dois** módulos — `capabilities` (com
`contracts.py`, `niches.py`, `registry.py`, `service.py`) e `governance` (só
`contracts.py`).

O que existe fora: `app/services/` com 37 serviços planos e `app/models/` com 25
arquivos planos, incluindo domínios inteiros — negociação, provider, produção,
transferência, recebíveis, fiscal, conciliação — que nunca receberam fronteira
de módulo.

Consequência prática: a fronteira que o roadmap trata como obrigatória existe
para dois domínios e é convenção de nome para todos os outros. Nada impede um
serviço de importar o modelo de qualquer outro, e nada declara qual módulo é
dono de qual tabela.

Isto não é dívida de um sprint: atravessa todos. Registrado na seção 9 do
roadmap como dívida transversal.

## O que esta auditoria muda no próximo passo

Antes desta leitura, o Gate C parecia o próximo passo natural. Ele continua
sendo o único item que destrava simultaneamente o Gate D, o piloto S21 e o S22 —
mas agora com um detalhe que não estava visível: **o S9, de que o Gate C
depende, não tem tela de cadastro**. Fechar o Gate C provando a cadeia por teste,
sem que exista forma de configurar um provider pela interface, entregaria um
gate verde sobre uma funcionalidade que nenhum lojista consegue usar.

**Superado em 05/09/2026.** A tela de cadastro do S9 foi entregue, o Gate C já
havia sido promovido a `PASSED` em 04/09 e o próximo passo autorizado passou a
ser o **S13**, pelo mesmo argumento que esta auditoria usou contra o Gate C:
publicação em canal e conciliação de repasse são hoje uma janela sem maçaneta.
