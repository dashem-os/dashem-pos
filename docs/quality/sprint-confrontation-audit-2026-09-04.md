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
| S8 — Checkout Negotiation | 5 | sim | `/negotiations` | `test_s8_checkout_negotiation.py` | só no fluxo de mesa | **PARCIAL** |
| S9 — Providers e TEF Bridge | 7 | sim | `/providers` | `test_s9_payment_providers.py` | **nenhuma de cadastro** | **PARCIAL** |
| S10 — Channel Hub | 4 | sim | `/channels` | `test_s10_channel_hub.py` | `ChannelHubWorkspace` | **entregue no gate interno** |
| S11 — Production e KDS | 6 | sim | `/production` | `test_s11_production_kds.py` | `KdsShell`, `DeviceManager`, `CatalogManager` | **entregue no gate interno** |
| S12 — Transferências | 1 + eventos | sim | `/transfers` | `test_s12_transfers.py` | só transferência de item | **PARCIAL** |
| S13 — Channel Catalog | 6 | sim | `/channel-catalog` | `test_s13_channel_catalog_reconciliation.py` | **nenhuma** | **PARCIAL** |
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

### S12 — Transferências e Comandas Avançadas · PARCIAL

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

Falta, confrontado com as entregas declaradas:

- **comanda → comanda**: mover uma `Order` inteira entre sessões sem mesclar as
  sessões não tem operação própria;
- **separação de sessões**: o roadmap pede "junção e separação"; só a junção
  existe;
- **tela**: `mergeSessions` não é chamado por nenhum componente. A junção de
  mesas só acontece por API, o que na prática significa que o garçom não tem
  como juntar duas mesas.

### S13 — Channel Catalog e Marketplace Reconciliation · PARCIAL

Seis modelos, serviço, endpoint e teste existem. **Nenhuma tela consome.** A
publicação de catálogo em canal e a conciliação de repasse de marketplace são
hoje funcionalidades sem interface.

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
