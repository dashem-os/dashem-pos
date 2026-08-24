# Roadmap Canônico V2 — Dashem Commerce OS / Dashem POS

Status: **diretriz canônica para a próxima fase de construção**  
Data: 23 de agosto de 2026  
Revisão: **S14 concluído — próximo gate S15 Recebimentos, Cobrança e Renegociação**
Substitui como referência de execução qualquer sequência anterior que conflite com este documento.

## 1. Por que este roadmap existe

O Dashem não será desenvolvido como uma sucessão de telas. Cada sprint deve
resolver um trabalho real, sobre contratos de domínio estáveis, mantendo
isolamento, autorização, auditoria, persistência e operação multi-site.

Este roadmap consolida:

- a fundação já implementada no repositório;
- as pendências registradas no `README.md`;
- o fluxo visual Administrador → PDV → Comanda → Produção → Caixa → BI;
- o primeiro mercado: Food Service / Quick Service;
- a evolução futura para varejo, redes e canais externos;
- a responsabilidade real do Platform Owner e do administrador do tenant;
- a separação entre capabilities comerciais e permissões de usuário;
- a obrigação de modularizar desde o início, sem microserviços prematuros;
- a definição de pronto baseada em comportamento verificável, não na presença de uma tela.

## 2. Vocabulário canônico

Os termos abaixo não são intercambiáveis.

### 2.1 Dashem Control

É a superfície interna do SaaS. Sua rota canônica atual é:

```text
/owner
```

O nome da experiência é **Dashem Control**. O principal ator é o
**Platform Owner**. A rota `/owner` não representa o dono do estabelecimento e
não é uma área administrativa do cliente.

### 2.2 Platform Owner

É o gestor do SaaS Dashem. Administra clientes enquanto organizações
contratantes, não a equipe operacional interna desses clientes.

Pode:

- cadastrar, editar, pausar, reativar, suspender e arquivar tenants;
- administrar ficha contratual, classificação, plano, limites e capabilities;
- criar matriz e estruturas contratadas durante implantação;
- entregar, reenviar, suspender ou revogar o acesso do administrador contratual;
- acompanhar onboarding, saúde, integrações, incidentes e auditoria;
- executar suporte assistido apenas quando explícito, temporário e auditado.

Não pode, como rotina operacional:

- cadastrar caixas, atendentes, supervisores ou gerentes do cliente;
- organizar escalas ou equipes do estabelecimento;
- definir permissões cotidianas em nome do administrador do tenant;
- operar vendas, estoque, mesas, comandas ou caixa do cliente.

### 2.3 Dashem Gestão

É a superfície administrativa do cliente:

```text
/manage
```

Seu principal ator é o **Tenant Administrator**. Ele administra:

- equipe e permissões;
- unidades dentro dos limites contratados;
- catálogo, preços e estoque;
- formas de pagamento e configurações operacionais;
- clientes, recebíveis, relatórios e indicadores do negócio.

### 2.4 Dashem POS

É a superfície operacional de venda:

```text
/pos
```

Seu ator é operador, caixa ou atendente. Deve privilegiar velocidade, touch,
teclado, leitor e baixa carga cognitiva. Não exibe infraestrutura ou funções
administrativas.

### 2.5 Dashem KDS

É a superfície de produção:

```text
/kds
```

Seu ator é cozinha, bar, copa ou outro ponto de produção. Não é um modo visual
do carrinho do PDV: possui filas, roteamento, estados e concorrência próprios.

### 2.6 Tenant, Store e Terminal

```text
Tenant (organização contratante)
└── Store (matriz, filial ou unidade operacional)
    └── Terminal (caixa, dispositivo ou estação operacional)
```

O modelo inicial `Tenant → Store → Register` será preservado. `Register` pode
ser apresentado como Terminal/Caixa na experiência do produto. Uma entidade
de dispositivo será criada somente quando identidade de hardware, pareamento
ou telemetria exigirem um contrato separado.

## 3. Contratos inegociáveis

### C1 — Isolamento entre tenants

1. O JWT prova identidade, nunca autorização comercial.
2. O backend resolve `User`, membership ativa, papel, tenant e store.
3. O frontend nunca inventa tenant ou store autorizado.
4. Toda tabela de tenant possui `tenant_id`.
5. Toda operação local possui `store_id` quando aplicável.
6. PostgreSQL RLS é forçado e o runtime não possui `BYPASSRLS`.
7. Toda nova tabela multi-tenant nasce com policy, índices e teste negativo.
8. Nenhum filtro frontend ou ORM substitui RLS.

Selecionar um contexto entre memberships autorizadas é uma decisão de UX. Ler
ou alterar o tenant vizinho é uma violação de segurança. São problemas
diferentes e possuem gates diferentes.

### C2 — Contexto operacional explícito

Nenhuma interface pode escolher silenciosamente o primeiro tenant, a primeira
unidade ou o primeiro terminal retornado.

O contexto deve ser resolvido por:

```text
identidade
→ memberships ativas
→ tenant selecionado ou único
→ store selecionada ou única
→ terminal selecionado ou pareado
```

Quando existir somente uma opção, a seleção automática é permitida e deve ser
registrada no estado da sessão. Com múltiplas opções, a escolha é obrigatória.

### C3 — Capabilities comerciais não são permissões

Dois vocabulários independentes serão mantidos:

```text
Product Capability / Entitlement
inventory, kitchen_routing, modifiers, tef, receivables

Authorization Permission / Grant
catalog.read, catalog.update, sale.discount, cash.close
```

- `TenantCapability` define o que foi contratado e está disponível.
- `Permission` define o que uma pessoa pode fazer.
- uma permissão não ativa um módulo não contratado;
- uma capability não concede autorização a um usuário;
- a decisão efetiva exige entitlement + contexto + grant.

### C4 — Modularização desde o início

O backend continuará como monólito modular. Cada módulo possui:

- modelos e migrations;
- comandos e consultas;
- schemas de API;
- serviço de domínio;
- permissões exigidas;
- regras de auditoria e eventos;
- testes unitários, integração e isolamento;
- contribuição explícita para métricas e saúde quando aplicável.

O frontend será dividido por experiência e domínio, não por uma árvore global
de componentes dependente de um único contexto.

### C5 — Core transacional preservado

Não reconstruir sem evidência de falha:

- snapshots comerciais de itens;
- preço resolvido no servidor;
- estoque e ledger de movimentos;
- locks e concorrência de checkout/pagamento;
- split payment e confirmação atômica;
- caixa derivado do livro razão;
- idempotência e correlation IDs;
- auditoria e transactional outbox;
- RLS e separação da autoridade de migrations.

Refactoring deve manter testes de caracterização verdes antes e depois.

### C6 — Escrita normalizada, leitura orientada à tarefa

Separar módulos de escrita não obriga o frontend a executar N consultas.

O PDV receberá uma projeção paginada de disponibilidade:

```text
SellableProduct
├── produto
├── categoria
├── preço efetivo da store/canal
├── saldo e estoque mínimo
├── disponibilidade
├── favoritos/acesso rápido
└── modifiers/combos aplicáveis
```

Preço e estoque continuam com autoridades próprias, mas a consulta operacional
é composta no backend. Nenhum catálogo grande será carregado integralmente.

### C7 — Order não é Sale

```text
Order = intenção e execução operacional
Sale  = fechamento comercial e financeiro
```

Uma mesa pode permanecer aberta, receber várias ondas de itens, enviar itens a
pontos diferentes, transferir consumo e receber pagamentos parciais antes do
fechamento. O agregado `Order` será criado antes de Mesas/KDS e será ligado a
`Sale` no momento apropriado.

### C8 — Sem caminhos falsos

- cadastro de teste usa o mesmo domínio de um cliente;
- estado vazio permanece vazio;
- serviço não instrumentado aparece como não instrumentado;
- favoritos não são “os primeiros seis produtos”;
- estoque baixo usa `minimum_stock`, não um número visual fixo;
- categoria vem do relacionamento real, não da descrição;
- providers falsos são permitidos somente em ambiente de teste e devem estar identificados.

### C9 — Definition of Done

Uma sprint funcional exige, quando aplicável:

```text
UI
+ API
+ persistência/migration
+ permission/grant
+ tenant/store scope
+ auditoria
+ estados e transições
+ erros e empty states
+ testes automatizados
+ documentação do contrato
```

Para mutações críticas:

```text
+ idempotência
+ concorrência
+ outbox/eventos
+ rollback verificável
```

## 4. Estado e leitura honesta da fundação após o S7

### 4.1 O que já está cravado e protegido pelo CI

- Supabase Auth desacoplado do usuário interno;
- memberships de plataforma separadas das memberships de tenant;
- contexto tenant/store/terminal explícito e validado no backend;
- RLS forçado, runtime restrito e testes negativos entre tenants e stores;
- Alembic como autoridade exclusiva do schema;
- Permission Engine contextual separado do Capability Mesh;
- shells independentes para Control, Gestão, POS e KDS;
- `SellableProduct` paginado com preço, estoque, categoria e acesso rápido reais;
- operação COUNTER recuperável por store, terminal e operador;
- `Order` e `OrderItem` separados de `Sale`, com snapshots e comandos idempotentes;
- `ServiceTable`, `TableSession` e `Order` como contratos distintos;
- uma sessão de atendimento capaz de agrupar várias comandas;
- concorrência de abertura de mesa, isolamento, auditoria e outbox testados;
- estoque e caixa apoiados em ledger, sem saldo autoritativo inventado no browser;
- Console Owner persistente para ficha, lifecycle, estruturas, contrato e saúde inicial.

Essa é uma boa fundação porque as fronteiras de autoridade, isolamento e
transação já existem e são exercitadas. Isso não significa que todos os
domínios do produto estejam prontos. **Fundação sólida não é sinônimo de prédio
concluído.** KDS, negociação financeira, TEF, Channel Hub, recebíveis e BI ainda
precisam ser construídos sobre esses contratos, sem contorná-los.

### 4.2 O que será evoluído, não descartado

- o motor atual de `Payment`, split, parcial e troco será preservado por testes
  de caracterização e incorporado ao `Payment Orchestrator`;
- o fluxo atual de `Sale` continuará atendendo compatibilidade enquanto
  `CheckoutNegotiation` passa a governar o fechamento de `Order` e
  `TableSession`;
- caixa, estoque, fiscal, auditoria e outbox serão estendidos, não reescritos
  por preferência estética;
- a estrutura física dos diretórios poderá mudar de forma incremental, mas os
  limites modulares passam a valer imediatamente;
- integrações reais dependentes de contrato, credencial, homologação ou
  hardware terão gate interno separado do gate externo, sem providers falsos
  em produção.

### 4.3 Onde deliberadamente não seguiremos o desenho ao pé da letra

O desenho é contrato de experiência e fluxo de trabalho; ele não é um diagrama
de persistência. Quando uma solução de domínio for mais segura e extensível,
preservaremos o comportamento visual usando contratos melhores por baixo:

1. **Mesa não é comanda.** `ServiceTable` representa o recurso físico,
   `TableSession` representa o atendimento e cada `Order` representa uma
   comanda. Isso permite várias comandas, transferência e histórico sem
   transformar uma mesa em um pedido mutável.
2. **Saldo zero não libera mesa.** Pagamento cobre a obrigação financeira, mas
   o encerramento do atendimento continua explícito e verifica impedimentos
   operacionais.
3. **Negociação não é renegociação.** `CheckoutNegotiation` governa o fechamento
   atual da conta; `ReceivableAgreement` tratará posteriormente dívidas e
   renegociações sem alterar documentos originais.
4. **TEF não é regra de venda.** O `Payment Orchestrator` cria e acompanha cada
   parcela; o TEF executa somente parcelas de cartão por adapter/bridge.
5. **O navegador não conversa diretamente com DLL ou pinpad.** Um protocolo
   local autenticado do `Dashem TEF Bridge` isola SDK nativo, timeout e
   recuperação sem transformar o POS web em desktop monolítico.
6. **Marketplace não cria uma segunda lógica de pedidos.** O `Channel Hub`
   persiste, deduplica e normaliza eventos externos antes de entregá-los ao
   mesmo `Order Engine` usado por balcão e mesa.
7. **Pagamento online de marketplace não é TEF.** Ele nasce como pagamento do
   provider, com repasse e conciliação próprios; jamais é fingido como cartão
   local.
8. **Módulo não significa microserviço.** Continuaremos em monólito modular até
   carga, risco ou autonomia operacional justificarem extração.
9. **Frontend não recompõe verdade financeira.** Read models do backend entregam
   totais, saldo, disponibilidade e estados; a UI apenas orienta o trabalho.

Essas decisões não são liberdade para improvisar. Qualquer desvio futuro de um
contrato aceito exige ADR, migration, compatibilidade e gate automatizado.

### 4.4 Domínios ainda não concluídos

- `CheckoutNegotiation` e integração canônica entre Orders, Sale e pagamentos;
- Payment Orchestrator, allocations e providers desacoplados;
- protocolo e bridge TEF, seguido de homologação por provider;
- production routing, tickets e KDS operacional;
- transferências de mesa, comanda e item com conservação e linhagem;
- Channel Hub, catálogo por canal e reconciliação de marketplace;
- recebíveis, acordos, cobrança e renegociação;
- BI multi-site com projeções e drill-down;
- observabilidade completa e conclusão operacional do Dashem Control.

## 5. Arquitetura modular alvo

```text
backend/app/modules
├── platform          tenants, planos, contratos, onboarding e suporte
├── identity          usuários, auth identities e memberships
├── authorization     permissions, grants, role profiles e policies
├── organization      stores, regions futuras, terminals e devices
├── capabilities      contratos, entitlements, profiles e overrides
├── catalog           produtos, categorias, modifiers e combos
├── pricing           preços efetivos, tabelas, promoções e canais
├── inventory         saldo, ledger, reservas e reposição
├── orders            pedidos, itens, origem e fulfillment
├── table_service     mesas, comandas, junções e transferências
├── production        routing, tickets, filas e KDS
├── sales             fechamento comercial e snapshots
├── negotiation       conta, ajustes, cobertura e fechamento
├── payments          intents, allocations, confirmações e estornos
├── receivables       crediário, parcelas, liquidações e acordos
├── cash              sessões e livro razão do caixa
├── fiscal            documentos e eventos fiscais
├── channel_hub       inbox, normalização, deduplicação e catálogo por canal
├── reporting         projeções, métricas e drill-down
├── integrations      adapters TEF, PIX, fiscal, delivery e device bridge
└── reliability       auditoria, outbox, idempotência e observabilidade
```

Não é necessário mover todos os arquivos fisicamente antes da funcionalidade.
Cada sprint deve, porém, respeitar esses limites e impedir novos acoplamentos.

Frontend alvo:

```text
frontend/src
├── app               sessão, roteamento e bootstrap
├── shared            design system, feedback e infraestrutura de UI
├── control           experiência /owner
├── manage            experiência /manage
├── pos               experiência /pos
├── kds               experiência /kds
└── domains
    ├── organization
    ├── authorization
    ├── catalog
    ├── inventory
    ├── orders
    ├── production
    ├── negotiation
    ├── payments
    ├── receivables
    ├── channels
    └── cash
```

## 6. Contratos dos principais agregados

```text
Tenant
├── TenantSubscription
├── TenantCapability
├── Store
│   ├── Terminal/Register
│   ├── ServiceTable
│   └── ProductionPoint
└── Membership
    └── PermissionGrant / RoleProfile

TableSession
├── ServiceTable opcional
├── Order 1..N
│   └── OrderItem 1..N
│       ├── CommercialSnapshot
│       ├── ModifierSnapshot
│       └── ProductionAllocation 0..N
└── TransferRecord 0..N

CheckoutNegotiation
├── Order(s) cobertos
├── TotalSnapshot
├── Adjustment(s): taxa, desconto e acréscimo autorizados
├── PaymentAllocation 0..N
│   ├── PaymentIntent
│   ├── Payment confirmado opcional
│   └── ProviderTransaction opcional
├── ReceivableAllocation opcional
└── Sale/FiscalDocument no fechamento

ChannelInboxEvent
├── provider + merchant + external_event_id
├── payload persistido e versão do adapter
├── acknowledgment posterior à persistência
└── ExternalOrderMapping → Order canônico
```

Estados canônicos da negociação:

```text
OPEN → PARTIALLY_COVERED → COVERED → FINALIZING → FINALIZED
  └───────────────────────────────→ CANCELED, quando permitido
```

Estados canônicos de uma intenção de pagamento:

```text
CREATED → PROCESSING → CONFIRMED
                    ├→ FAILED
                    ├→ CANCELED
                    └→ UNKNOWN, exigindo consulta/reconciliação
```

Invariantes:

1. item transferido nunca desaparece; gera origem, destino, ator, motivo e horário;
2. produção não altera preço, snapshot comercial ou total financeiro;
3. cada valor confirmado é alocado uma única vez à negociação;
4. parcelas confirmadas permanecem válidas se uma parcela posterior falhar;
5. pagamento confirmado nunca excede o saldo devido sem regra explícita de troco;
6. `COVERED` significa cobertura financeira; não encerra sozinho `TableSession`;
7. `FINALIZED` exige cobertura integral, Sale consistente e gates fiscal/caixa aplicáveis;
8. recebível não altera silenciosamente o documento original;
9. pagamento de marketplace e transação TEF possuem ciclos de conciliação distintos;
10. caixa esperado vem exclusivamente do ledger;
11. capability e permission são avaliadas no servidor em toda mutação;
12. toda transição crítica é versionada, auditável, idempotente e acompanhada de outbox.

### 6.1 Gates transversais obrigatórios a partir do S8

Estes requisitos não pertencem ao último sprint de hardening. Eles bloqueiam a
conclusão de **cada** sprint funcional:

- RLS e teste negativo por tenant/store em toda tabela nova;
- permission e capability independentes, avaliadas no backend;
- idempotência com rejeição de payload divergente;
- controle de concorrência e versão em toda mutação crítica;
- auditoria, ator, motivo e outbox na mesma transação;
- regra financeira e total autoritativo somente no servidor;
- estado vazio, indisponível, degradado, conflito e retry reais na UI;
- adapter externo fora do caminho crítico da venda local;
- telemetria mínima: latência, falha, backlog, retry e última sincronização;
- provider fake ou fixture somente em teste, nunca como aparência de integração real;
- migration `upgrade/downgrade/check`, testes e CI verdes antes do próximo sprint.

## 7. Roadmap de execução

### S0 — Baseline, contratos e testes de caracterização

Objetivo: congelar o comportamento correto e registrar decisões antes do refactoring.

Entregas:

- este roadmap adotado como referência;
- ADR `Order versus Sale`;
- ADR `Capability versus Permission`;
- inventário de endpoints e estados atuais;
- testes frontend de login, roteamento, seleção de contexto, carrinho, split e caixa;
- contract tests para APIs consumidas pelo frontend;
- matriz dos testes backend que protegem venda, estoque, pagamento e isolamento.

Gate:

- comportamento crítico coberto antes de mover responsabilidades;
- CI verde em banco vazio e migrado;
- nenhuma regra importante depende apenas de teste manual.

### S1 — Product Reframe e modularização frontend

Objetivo: separar definitivamente as quatro experiências.

Entregas:

- `/login`, `/owner`, `/manage`, `/pos` e `/kds` com guards próprios;
- shells e bundles independentes dentro do mesmo frontend;
- diagnóstico técnico removido do Gestão;
- design tokens e componentes compartilhados;
- personalidade Control, Gestão, POS e KDS sem duplicar primitives;
- decomposição inicial do `PosContext` e do cliente de API por domínio.

Gate:

- operador não acessa menu administrativo;
- cliente não vê infraestrutura;
- Platform Owner não entra no fluxo normal do tenant;
- reload e deep link preservam a rota correta.

### S2 — Contexto organizacional e Permission Engine

Objetivo: resolver acesso SaaS e autorização profissional.

Entregas:

- seletor explícito de tenant/store/terminal quando houver múltiplas opções;
- auto-seleção somente quando a opção autorizada for única;
- `permissions`, `role_profiles`, `role_profile_permissions` e grants necessários;
- permissions canônicas (`catalog.update`, `sale.discount`, `cash.close`, etc.);
- avaliação `entitlement + context + permission` no backend;
- frontend recebe capabilities e permissions efetivas;
- Console Owner limitado ao administrador contratual e ações de segurança/contrato;
- gestão da equipe movida para o tenant admin.

Gate:

- operador vende, mas não altera catálogo/preço-base;
- caixa não concede permissões;
- Tenant Admin cria equipe dentro dos limites contratados;
- usuário multi-tenant nunca opera em contexto implícito incorreto;
- matriz negativa cobre tenant, store, role e permission.

### S3 — Dashem Gestão Shell

Objetivo: criar o Business Console real do cliente.

Entregas:

- Visão Geral;
- Vendas, Pedidos, Mesas & Comandas e Caixas;
- Produtos, Categorias, Estoque e Clientes;
- Recebimentos e Movimentações;
- Unidades, Equipe e Permissões;
- Pagamentos, Impressoras, Fiscal e Integrações;
- menus filtrados por capability e permission;
- dashboard via consultas agregadas do backend.

Gate:

- o gestor entende faturamento, vendas, ticket, caixa e alertas sem termos técnicos;
- menus ocultos também são negados pelo backend;
- métricas rastreáveis até dados persistidos.

### S4 — Catálogo, Pricing e Inventory Read Model

Objetivo: fornecer catálogo operacional completo e escalável.

Entregas:

- CRUD de categoria, subcategoria e produto;
- imagem, unidade, SKU, barcode, custo, preço, margem e disponibilidade;
- estoque atual e mínimo por store;
- paginação e busca server-side;
- projeção `SellableProduct` sem N+1;
- favoritos/acesso rápido persistidos por store/perfil;
- alertas derivados de `quantity <= minimum_stock`;
- modifiers, modifier groups, combos, multi-flavor e destination;
- eventos para mudanças relevantes.

Gate:

- produto criado no Gestão aparece no POS da store autorizada;
- preço e saldo efetivos vêm do backend;
- catálogo grande não é carregado integralmente;
- nenhum fallback semântico usa descrição ou posição da lista.

### S5 — Frente de Caixa COUNTER

Objetivo: consolidar o PDV atual como superfície profissional de balcão.

Entregas:

- contexto explícito de store/terminal/operator;
- busca por nome, SKU e barcode via projeção paginada;
- teclado, touch e scanner;
- carrinho, quantidade, desconto e cancelamento com permissions;
- recuperação segura da operação em andamento;
- modos `COUNTER` e `TAKEAWAY`;
- estados offline/degradado explícitos sem perda silenciosa.

Gate:

- operador inicia venda e chega ao pagamento sem Gestão;
- nenhuma regra financeira depende do navegador;
- tempo e número de ações são medidos.

### S6 — Order Foundation

Objetivo: criar o núcleo operacional anterior ao fechamento financeiro.

Entregas:

- `Order`, `OrderItem`, snapshots de modifiers e estados;
- origem, canal, fulfillment e idempotency key;
- vínculo opcional com customer, table e sale;
- múltiplos lançamentos no mesmo order;
- comandos idempotentes para adicionar, alterar e cancelar item;
- outbox de order/item.

Gate:

- um order pode permanecer aberto e receber novos itens;
- retry não duplica item;
- venda de balcão continua funcionando durante a introdução do agregado.

### S7 — Mesas e Comandas

Objetivo: implementar o workflow Food Service de atendimento.

Entregas:

- `ServiceTable` como recurso físico com estados `AVAILABLE`, `OCCUPIED`,
  `RESERVED` e `BLOCKED`;
- `TableSession` como ciclo de atendimento, separado da mesa física, com estados
  `OPEN`, `IN_SERVICE`, `PARTIALLY_PAID`, `CLOSING`, `CLOSED` e `CANCELED`;
- abertura idempotente de mesa ou comanda individual sem mesa;
- uma sessão pode agrupar uma ou mais comandas (`Order`) sem confundir
  ocupação, consumo, fechamento financeiro e disponibilidade física;
- lançamento incremental, múltiplas ondas de itens e conta consolidada no
  backend;
- vínculo explícito de cliente e atendente;
- versão esperada e bloqueio transacional definidos por comando;
- projeção operacional de mesas e sessões sem cálculo autoritativo no browser;
- histórico operacional, auditoria e outbox transacional;
- isolamento RLS por tenant e store e capability `table_service` independente
  de permission.

Gate:

- abrir mesa → criar sessão → lançar → adicionar depois → consultar total
  consolidado persistido;
- abrir comanda individual sem criar mesa fictícia;
- duas aberturas concorrentes não ocupam a mesma mesa nem criam duas sessões
  ativas;
- retry com a mesma chave não duplica sessão, comanda ou lançamento e payload
  divergente é rejeitado;
- dois operadores não sobrescrevem consumo silenciosamente;
- uma sessão aceita mais de uma comanda sem impor `uma mesa = um order`;
- tenant ou store diferente não consulta nem altera mesa, sessão ou comanda;
- `PARTIALLY_PAID` é estado da sessão/conta e nunca estado físico da mesa;
- saldo zero não libera mesa automaticamente: o encerramento é explícito e
  rejeitado enquanto existirem impedimentos operacionais;
- toda mutação registra ator, contexto, idempotência, auditoria e outbox;
- a interface usa somente dados persistidos e mantém estados vazios reais, sem
  fixtures ou conteúdo hardcoded.

### S8 — Checkout Negotiation e Payment Orchestrator

Objetivo: criar a autoridade única da conta e incorporar o motor financeiro já
existente sem confundir consumo, cobertura financeira e encerramento da mesa.

Entregas:

- `CheckoutNegotiation` vinculada a uma `TableSession` ou a um ou mais Orders;
- snapshot server-side de subtotal, taxas, descontos, acréscimos e total devido;
- uma negociação ativa por escopo de fechamento, com versão e lock;
- `PaymentIntent`, `PaymentAllocation` e saldo restante autoritativo;
- incorporação dos pagamentos atuais de dinheiro, PIX e cartão manual ao
  orchestrator, preservando idempotência, split, parcial e troco;
- split por valor, pessoa ou seleção de itens quando aplicável, com allocations
  rastreáveis até a obrigação coberta;
- parcelas independentes: falha posterior não desfaz confirmação anterior;
- projeção única para POS: total, pago confirmado, em processamento, falhou e
  falta pagar;
- transição de `TableSession` para `PARTIALLY_PAID` sem alterar o estado físico
  da mesa;
- finalização explícita, com Sale e snapshots consistentes, somente após
  cobertura integral e gates aplicáveis.

Gate:

- conta de R$ 64,90 aceita R$ 10 em dinheiro + R$ 20 em outro meio e permanece
  aberta com R$ 34,90 de saldo;
- falha na terceira parcela preserva as duas primeiras e permite retomada;
- dois pagamentos concorrentes não ultrapassam o devido;
- retry não duplica intent, confirmação, allocation, movimento de caixa ou Sale;
- alteração do consumo invalida ou versiona negociação ainda não finalizada,
  sem recalcular silenciosamente uma conta observada anteriormente;
- saldo zero isolado não libera mesa e finalização rejeita impedimento operacional;
- tenant/store diferente não lê nem altera negociação ou pagamento;
- UI não calcula o saldo autoritativo e não cria pagamento apenas para simular fluxo.

### S9 — Payment Providers e Dashem TEF Bridge

Objetivo: executar parcelas por providers intercambiáveis sem colocar SDK nativo
ou indisponibilidade externa dentro da regra de venda.

Entregas:

- contrato `PaymentProviderAdapter` para iniciar, consultar, cancelar e estornar;
- `ProviderTransaction` com provider, NSU, autorização, adquirente, bandeira,
  transaction ID, terminal e payload sanitizado;
- estados `CREATED`, `PROCESSING`, `CONFIRMED`, `FAILED`, `CANCELED` e `UNKNOWN`;
- protocolo versionado do `Dashem TEF Bridge`, com pareamento do terminal,
  autenticação local, correlation ID, timeout e retomada;
- adapter TEF separado do adapter do provider homologado (`SiTef`, `PayGo`,
  `Cappta` ou futuro);
- POS conversa apenas com API/bridge, nunca diretamente com DLL, SDK ou pinpad;
- modo cartão manual explicitamente identificado e auditado quando permitido;
- consulta e reconciliação obrigatórias para resultado desconhecido;
- simulador de provider somente em testes automatizados;
- telemetria de bridge: online, versão, provider, última operação e erro sanitizado.

Gate interno, independente de homologação comercial:

- uma parcela TEF aprovada confirma somente sua allocation;
- timeout não vira falha definitiva nem confirmação presumida;
- retry consulta a transação anterior antes de criar outra cobrança;
- TEF offline não derruba dinheiro, PIX, crediário ou operação local;
- navegador nunca recebe segredo, credencial do provider ou acesso ao SDK;
- sem bridge/provider configurado a UI mostra `não configurado`, nunca sucesso falso.

Gate externo para ativação produtiva de cada provider:

- contrato, credenciais, hardware e ambiente de homologação disponíveis;
- certificação do fluxo, impressão, cancelamento, estorno e reconciliação concluída;
- capability específica liberada somente para combinação homologada de
  tenant/store/terminal/provider.

### S10 — Dashem Channel Hub e External Order Inbox

Objetivo: receber origens externas no mesmo Order Engine sem criar uma segunda
lógica de pedidos ou colocar marketplace no caminho crítico local.

Entregas:

- `Channel`, `MerchantConnection`, `ChannelInboxEvent` e
  `ExternalOrderMapping`;
- adapters versionados para iFood, 99Food e canais futuros;
- autenticação e secrets fora do payload de domínio e dos logs;
- persistência do evento antes do acknowledgment;
- deduplicação por provider/merchant/external event e order ID;
- normalização de origem, fulfillment, cliente, itens, modifiers e observações;
- criação do Order canônico pelo mesmo serviço usado por COUNTER/TABLE;
- status outbound via outbox, retry e dead-letter observável;
- pagamento online de marketplace como provider `MARKETPLACE`, nunca TEF;
- harness/fixtures de contrato somente em testes quando credenciais externas não
  estiverem disponíveis.

Gate interno:

- replay do mesmo evento não duplica Order ou item;
- evento só recebe acknowledgment após persistência durável;
- payload inválido fica em quarentena com motivo, sem order parcial;
- falha de iFood/99Food não impede venda local;
- Order externo nasce no contrato canônico, sem bifurcar a lógica de venda; o
  gate ponta a ponta de produção é concluído no S11;
- marketplace pago online não cria transação de cartão local;
- nenhuma tela apresenta canal conectado sem conexão real validada.

Gate externo por canal:

- credenciais, sandbox e autorização do merchant disponíveis;
- testes oficiais/certificação do provider concluídos;
- política de polling/webhook, rate limit e recuperação documentada.

### S11 — Production Routing e KDS

Objetivo: encaminhar cada item confirmado pelo Order Engine ao ponto correto de
produção, sem duplicação e sem acoplar cozinha ao fechamento financeiro.

Entregas:

- `ProductionPoint`: cozinha, bar, copa, expedição e impressora;
- regras persistidas por store, produto, modifier e fulfillment;
- `ProductionTicket` e `ProductionTicketItem` como allocations do `OrderItem`;
- dispatch idempotente por versão/onda do item, independentemente da origem;
- estados `NEW`, `ACCEPTED`, `PREPARING`, `READY`, `DELIVERED`, `CANCELED`;
- `/kds` com filas reais, tempo, prioridade, operador e concorrência;
- cancelamento e alteração após envio com evento compensatório explícito;
- fallback de impressão somente quando contratado e configurado;
- projeção de produção no POS e no Channel Hub sem mutar preço ou total.

Gate:

- COUNTER, TABLE e canal externo usam a mesma regra de roteamento;
- item aparece uma única vez em cada destino aplicável;
- modifier pode alterar destino sem duplicar o item comercial;
- duas telas KDS não sobrescrevem transição silenciosamente;
- reenvio após timeout é idempotente;
- KDS ou impressora indisponível mantém Order íntegro e backlog observável;
- produção nunca altera snapshot comercial ou saldo da negociação;
- toda transição registra ator/dispositivo, horário, versão e outbox.

### S12 — Transferências e Comandas Avançadas

Objetivo: mover responsabilidade operacional sem apagar origem, consumo ou
trajetória de produção/pagamento.

Entregas:

- transferência mesa → mesa, comanda → comanda e item → comanda;
- junção e separação de sessões com comandos explícitos;
- `TransferRecord` imutável com origem, destino, quantidade, ator e motivo;
- split de quantidade com identidade derivada e vínculo ao item original;
- regras para itens já enviados, prontos, parcialmente pagos ou em fechamento;
- bloqueio/compensação quando produção, negociação ou fiscal tornam a operação
  incompatível;
- projeção da linhagem no POS e Gestão.

Gate:

- quantidade e valor são conservados antes/depois da transferência;
- histórico reconstrói toda a trajetória sem consultar log textual;
- transferência concorrente possui um vencedor e conflito visível;
- item coberto por pagamento não muda de obrigação silenciosamente;
- junção não cria duas sessões ativas para a mesma mesa;
- isolamento tenant/store e permissions são testados negativamente.

### S13 — Channel Catalog e Marketplace Reconciliation

Objetivo: manter um catálogo canônico e tratar venda de marketplace separada do
repasse financeiro do marketplace.

Entregas:

- mapeamento de produto, categoria, modifier e opção Dashem ↔ provider;
- preço, disponibilidade e estoque publicáveis por canal/store;
- jobs de publicação idempotentes com versão, backlog e resultado por item;
- disponibilidade alterada uma vez no Dashem e propagada aos canais habilitados;
- divergências e conflitos de catálogo visíveis para correção, sem duplicar SKU;
- `MarketplaceSettlement` com bruto, comissão, taxa, promoção, ajuste, previsto e pago;
- importação/conciliação separada de pagamento operacional;
- projeção financeira por canal e competência.

Gate:

- um produto Dashem mantém identidade única com vários IDs externos;
- falha parcial de publicação não marca lote inteiro como sincronizado;
- retry não duplica item ou modifier no provider;
- Order continua aceito segundo política explícita se a sincronização estiver atrasada;
- venda confirmada e repasse pendente aparecem como fatos distintos;
- diferenças de comissão/taxa são rastreáveis até documento do provider.

### S13.1 — Retaguarda Operacional do Tenant

Objetivo: tornar o Dashem Gestão a superfície administrativa real do tenant e
separar, por contrato e permission, configuração de operação cotidiana.

Entregas:

- navegação de Gestão organizada por visão, operação, mercadorias, estrutura e
  acessos, sem cards congelados ou referências de sprint no produto;
- workspaces persistidos para produtos/preços, categorias, estoque e movimentos;
- `ServiceArea`, configuração e arquivamento de mesas, reservas e estados de
  impedimento por unidade;
- `OperationalDevice` para POS, KDS e impressora, com caixa ou ponto de produção
  criado na mesma transação, heartbeat e ciclo `ACTIVE/PAUSED/REVOKED`;
- roteamento persistido produto → cozinha/bar/copa/expedição/impressão;
- dashboard com hierarquia de decisão, métricas reais, alertas e atalhos para
  tarefas administrativas;
- fronteira unidirecional: Gestão pode abrir o PDV; POS e KDS não expõem Gestão;
- PDV abre em todos os produtos quando não existem favoritos, sem tela vazia
  causada por fallback visual.

Gate:

- somente Gestão pode criar, editar, ordenar ou arquivar uma mesa;
- atendente pode bloquear/liberar mesa existente mediante permission e motivo;
- mesa reservada sinaliza cliente, horário e quantidade e exige confirmação da
  reserva antes de abrir a sessão;
- reserva, abertura, bloqueio, dispositivo e mudança de estado são auditáveis e
  isolados por tenant/store;
- criação de terminal e estrutura vinculada é atômica;
- telas vazias orientam a próxima ação sem inventar dados;
- frontend, backend, migration upgrade/downgrade/rebuild e drift check verdes.

### S14 — Crediário e Receivables

Estado: **concluído no gate interno**. A implementação mantém política e limite
por cliente no tenant, calcula exposição sob lock pessimista, cobre a negociação
com `ReceivableAllocation` e persiste Sale + título em uma única transação. O
principal é imutável; saldo/status são projeções do ledger. Estorno exige motivo,
ator e idempotência. Crédito não gera `Payment` nem numerário no caixa. A
capability `receivables` e as permissions canônicas delimitam leitura, emissão,
política e reversão. O mesmo trabalho corrigiu `source_version` para `BIGINT`,
necessário aos Orders de balcão que usam versão temporal em microssegundos.

Objetivo: converter parte autorizada do saldo em obrigação financeira sem
disfarçar ausência de pagamento.

Entregas:

- customer pessoa/empresa com política de crédito por tenant;
- limite, exposição, bloqueio e autorização com permission;
- `Receivable` com principal, pago, saldo, emissão, vencimento e status;
- `ReceivableAllocation` cobrindo explicitamente uma negociação;
- lançamento atômico entre negociação, Sale e recebível;
- eventos, ledger financeiro e projeção imediata no Gestão.

Gate:

- limite é validado com lock e duas vendas concorrentes não o ultrapassam;
- venda e recebível são atômicos;
- saldo convertido em conta não desaparece nem é contado como caixa recebido;
- cancelamento/estorno gera reversão rastreável, nunca edição destrutiva;
- cliente, saldo e documentos permanecem isolados por tenant.

### S15 — Recebimentos, Cobrança e Renegociação

Objetivo: liquidar ou renegociar recebíveis preservando integralmente sua origem.

Entregas:

- seleção de um ou vários recebíveis;
- liquidação total/parcial pelo Payment Orchestrator;
- juros, multa, desconto e abatimento com política e permission;
- `ReceivableAgreement` e parcelas vinculadas aos documentos originais;
- aging, vencidos, promessa e histórico de cobrança;
- baixa e estorno via ledger, sem alterar principal original.

Gate:

- cada mudança possui ator, permission, motivo, versão e trilha;
- documentos originais permanecem imutáveis;
- split de recebimento não duplica baixa;
- acordo soma exatamente principal selecionado + ajustes autorizados;
- falha de uma parcela não apaga recebimentos anteriores.

### S16 — Cash, Fiscal e Financial Reconciliation Completion

Objetivo: integrar negociação, pagamentos, caixa e fiscal sobre os ledgers já
existentes, sem reconstruí-los.

Entregas:

- estados de caixa canônicos `CLOSED → OPEN → CLOSING → CLOSED`;
- opening, sale payment, sangria, reforço, refund e closing;
- conferência cega opcional e política de divergência;
- allocations em dinheiro geram movimento exatamente uma vez;
- cartão/PIX/marketplace não entram como numerário físico;
- vínculo entre negociação finalizada, Sale, FiscalDocument e CashSession;
- conciliação por provider sem alterar pagamento confirmado;
- contingência fiscal e retomada observáveis.

Gate:

- saldo esperado deriva exclusivamente do ledger;
- fechamento concorrente é protegido;
- divergência nunca é recalculada apenas no frontend;
- refund/estorno produz movimentos compensatórios e auditoria;
- falha fiscal respeita política configurada sem duplicar Sale ou documento;
- conciliação aponta diferença, mas não reescreve fato financeiro confirmado.

### S17 — Business Intelligence V1

Objetivo: transformar fatos e eventos persistidos em gestão multi-site.

Entregas:

- projeções server-side incrementais por período;
- faturamento, vendas, ticket, recebimentos e caixa;
- ocupação, tempo de mesa, consumo, pagamento parcial e fechamento;
- produção, backlog, tempo por ponto e cancelamentos;
- pagamentos por meio/provider, TEF e marketplace;
- produtos, estoque, ruptura, transferências e descontos;
- recebíveis, aging, acordos e liquidações;
- filtros tenant → região futura → store → terminal → operador → canal;
- drill-down até a fonte persistida e indicação de atualização da projeção.

Gate:

- toda métrica possui fórmula, fonte e competência documentadas;
- dashboards não carregam históricos inteiros no browser;
- projeção pode ser reconstruída sem alterar o core transacional;
- atraso da projeção é informado, nunca escondido com número inventado;
- tenant/store scope é testado em consulta agregada e drill-down.

### S18 — Dashem Control Completion

Objetivo: concluir o plano de controle sem invadir a gestão cotidiana do tenant.

Entregas:

- leads, conversão, ficha cadastral e lifecycle comercial;
- contratos, limites, capabilities, dependências e onboarding;
- entrega e lifecycle do administrador contratual;
- timeline de identidade e e-mail sem tokens;
- saúde de Auth, API, banco, outbox, workers, fiscal, TEF e canais;
- visão de backlog, última sincronização e erro sanitizado por tenant;
- suporte assistido temporário, incidentes e auditoria;
- Resend com domínio, SPF, DKIM, DMARC e webhooks quando houver domínio próprio.

Gate:

- cliente opera sem acessar o Control;
- Control não cria nem administra equipe cotidiana;
- capability altera disponibilidade contratual sem conceder permission pessoal;
- suporte possui motivo, prazo, escopo, aprovação e auditoria;
- saúde desconhecida aparece como não instrumentada, nunca verde presumido.

### S19 — Capability Profiles e Module Contributions

Objetivo: compor verticais e experiências sem forks, menus hardcoded ou módulos
cosméticos.

Entregas:

- profiles versionados `FOOD_SERVICE`, `RETAIL` e `GROCERY` futuros;
- dependências e conflitos de capability persistidos;
- configuração efetiva por tenant/store/terminal;
- contribution points de UI, rotas, permissions, health e reporting;
- migration segura de versão de contrato;
- histórico preservado quando módulo é desativado.

Gate:

- vertical é composição de módulos, não branch de código;
- módulo sem implementação não pode ser vendido/ativado;
- desativar capability remove comandos e navegação sem apagar histórico;
- permission sem entitlement continua negada e entitlement sem grant não autoriza;
- profile é atalho versionado de configuração, não nova fonte de verdade.

### S20 — Operational Hardening e Pilot Readiness

Objetivo: provar em conjunto as garantias que já foram exigidas sprint a sprint.

Entregas:

- cenários combinados de concorrência entre mesa, order, produção, pagamento,
  transferência e fechamento;
- chaos/retry para bridge, providers, Channel Hub, workers e conectividade;
- matriz completa tenant/store/terminal/permission/capability;
- rate limit, proteção de sessão, AAL e rotação de secrets;
- testes offline/degradado e recuperação sem perda silenciosa;
- SLOs, alertas, dashboards operacionais e runbooks;
- backup/restore, continuidade e rollback de migration exercitados;
- carga e volume com catálogo, orders, tickets e eventos representativos.

Gate:

- suíte crítica automatizada verde em banco vazio e migrado;
- nenhum caminho conhecido pode perder ou duplicar operação silenciosamente;
- RPO/RTO do piloto definidos e restore demonstrado;
- falha externa degrada somente sua capability;
- incidentes simulados possuem detecção, diagnóstico e procedimento de recuperação.

### S21 — Piloto Comercial

Objetivo: validar trabalho real em uma operação pequena com telemetria e suporte.

Perfil inicial:

- 1 estabelecimento;
- 1–3 caixas;
- 5–15 funcionários;
- balcão + mesas + cozinha;
- PIX, dinheiro e cartão manual ou TEF somente se homologado;
- canal externo somente se credenciado e certificado.

Medir:

- tempo e ações por tarefa;
- tempo até produção e entrega;
- pagamento parcial, cobertura e encerramento;
- erros, cancelamentos, transferências e divergências;
- backlog/retry de integrações e recuperação;
- estabilidade, clareza e percepção de velocidade.

Gate:

- decisões baseadas em operação observada e dados persistidos;
- ausência de contrato/hardware externo não é mascarada por integração fake;
- incidente crítico bloqueia expansão até correção e novo gate verde.

## 8. Dependências e ordem de execução

```text
FUNDAÇÃO CONCLUÍDA
S0 → S1 → S2 → S3 → S4 → S5 → S6 → S7

RETAGUARDA DO TENANT
S1 + S2 + S4 + S7 + S11 → S13.1 Gestão, mesas, reservas e dispositivos

FECHAMENTO E PROVIDERS
S7 + core financeiro existente → S8 CheckoutNegotiation/Orchestrator → S9 TEF

OPERAÇÃO FOOD SERVICE
S4 + S6 + S10 → S11 Production/KDS
S7 + S8 + S11 → S12 Transferências

OMNICHANNEL
S4 + S6 → S10 Channel Hub
S4 + S8 + S10 → S13 Channel Catalog/Reconciliation

CRÉDITO E FINANCEIRO
S8 → S14 Receivables → S15 Cobrança/Renegociação
S8 + S9 + S13 + S14 + S15 → S16 Cash/Fiscal/Reconciliation

GESTÃO E PLATAFORMA
S11 + S12 + S13 + S14 + S15 + S16 → S17 BI
S2 + fontes de saúde de S8–S17 → S18 Dashem Control Completion
capabilities reais de S9–S18 → S19 Capability Profiles

PILOTO
S8–S19 → S20 Hardening/Pilot Readiness → S21 Piloto Comercial
```

Os números registram a sequência recomendada de foco. S10 e partes internas do
S18 podem evoluir em paralelo quando houver capacidade, mas nenhum trabalho
paralelo pode mudar silenciosamente contratos do Commerce Plane. O S19 somente
consolida profiles depois de existirem implementações reais, evitando bundles
cosméticos. Gates externos de TEF ou marketplace podem permanecer pendentes sem
bloquear módulos locais; nesse caso a capability produtiva continua desativada
e aparece como `não configurada`, nunca como pronta.

## 9. Registro de dívidas, destino e estado

| Dívida/risco | Destino | Resultado obrigatório | Estado |
|---|---|---|---|
| Gestão e POS alternados por estado global | S1 | rotas e shells independentes | resolvido e testado |
| Diagnóstico técnico dentro do Gestão | S1 | somente no Control | resolvido e testado |
| Primeiro tenant/store/register escolhido silenciosamente | S2 | contexto explícito | resolvido e testado |
| RBAC grosso por papel/rota | S2 | permission grants granulares | resolvido no Permission Engine |
| Capability confundida com permission | S2 | decisão efetiva independente | resolvido e inegociável |
| Produtos, preços e saldos em N+1 | S4 | `SellableProduct` paginado | resolvido e testado |
| Favorito, estoque mínimo ou categoria por fallback visual | S4 | dados persistidos reais | resolvido e testado |
| Order confundido com Sale | S6 | agregados separados | resolvido e testado |
| Uma mesa tratada como um único pedido | S7 | `ServiceTable → TableSession → Orders` | resolvido e testado |
| Pagamento atual sem negociação canônica de Orders/sessão | S8 | `CheckoutNegotiation` + allocations | resolvido e testado |
| Provider/TEF acoplável à regra de venda | S9 | adapter + bridge + reconciliação | resolvido no gate interno; homologação externa pendente |
| Canal externo capaz de duplicar lógica de Order | S10 | inbox + normalização + deduplicação | resolvido no S10 |
| Produção representada apenas como estado visual do item | S11 | tickets e allocations persistidos | resolvido no S11 |
| Transferência capaz de apagar origem | S12 | linhagem e conservação imutáveis | resolvido no S12 |
| Catálogo duplicado por marketplace | S13 | mapeamento canônico por canal | resolvido no S13 |
| Gestão sem retaguarda e PDV capaz de retornar à administração | S13.1 | workspaces persistidos e fronteira unidirecional | resolvido e testado |
| Atendente capaz de cadastrar mesa ou abrir reserva sem confirmação | S13.1 | configuração exclusiva da Gestão + confirmação da reserva | resolvido e testado |
| Terminal e caixa/ponto criados em chamadas independentes | S13.1 | provisionamento transacional do dispositivo | resolvido e testado |
| Crediário tratado como pagamento recebido | S14 | recebível e allocation distintos | aberto |
| Renegociação capaz de alterar documento original | S15 | acordo e ledger imutáveis | aberto |
| Caixa/fiscal/provider sem conciliação unificada | S16 | fatos vinculados sem reescrita | aberto |
| BI agregado ou inventado no browser | S17 | read models rastreáveis | parcial, gate completo em S17 |
| Endpoint de identidade e saúde ainda amplos | S18 | routers e observabilidade por domínio | residual |
| Segurança/confiabilidade deixadas para o fim | contínuo + S20 | gate por sprint e prova combinada | política corrigida |

## 10. Política de execução

Antes de iniciar uma sprint:

1. confirmar dependências concluídas;
2. escrever casos de aceite e invariantes;
3. declarar aggregate root, autoridade dos dados e fronteiras com módulos existentes;
4. registrar ADR quando a solução deliberadamente diferir do desenho visual;
5. mapear migrations, rollback, policies RLS e índices;
6. definir permissions e capabilities aplicáveis;
7. definir eventos, auditoria, idempotência, lock e estratégia de retry;
8. separar gates internos de dependências externas/homologações;
9. listar estados de loading, vazio, erro, indisponível, retry e conflito.

Durante a sprint:

1. backend e frontend evoluem pelo mesmo contrato;
2. nenhuma UI antecede indefinidamente persistência e permission;
3. nenhuma mutação crítica nasce sem teste negativo;
4. mudanças estruturais possuem migration e rollback;
5. regras existentes só são substituídas com caracterização antes/depois;
6. integração externa não entra no caminho crítico local;
7. fixtures e simuladores ficam restritos a testes;
8. métricas não são inventadas para preencher espaço;
9. CI vermelho interrompe o avanço ao próximo sprint.

Ao concluir:

1. gate automatizado verde;
2. fluxo manual validado com dados reais de teste;
3. documentação e README atualizados;
4. CI e deployment observados;
5. dívida residual explicitamente registrada;
6. capability sem gate externo concluído permanece desativada;
7. “implementado” significa UI + API + persistência + autorização + testes, não mockup.

## 11. Próximo passo autorizado por este roadmap

O próximo ciclo de implementação deve ser:

```text
S15 — Recebimentos, Cobrança e Renegociação
```

S0–S14 estão concluídos nos gates internos. O S13 introduziu o ADR-009,
mapeamentos por merchant, ofertas versionadas, publicação item a item e documentos
de repasse independentes do Order. Falha parcial e diferença financeira ficam
observáveis. O S13.1 completa a primeira retaguarda operacional do tenant e fixa
a fronteira Gestão → PDV/KDS, nunca no sentido inverso. O S14 fecha o primeiro
contrato de crediário sem tratar obrigação como recebimento. O próximo gate
canônico é o S15.
