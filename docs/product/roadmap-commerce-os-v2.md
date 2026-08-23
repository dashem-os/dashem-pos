# Roadmap Canônico V2 — Dashem Commerce OS / Dashem POS

Status: **diretriz canônica para a próxima fase de construção**  
Data: 23 de agosto de 2026  
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

## 4. Estado da fundação em 23/08/2026

### 4.1 Fundação cravada e preservável

- Supabase Auth desacoplado do usuário interno;
- memberships de plataforma separadas das memberships de tenant;
- contexto tenant/store validado no backend;
- RLS forçado e testes negativos entre tenants e stores;
- Alembic como autoridade exclusiva do schema;
- venda, itens, snapshot de preço e checkout;
- estoque com razão e testes de concorrência;
- pagamentos confirmados, split, parcial e troco;
- caixa, sangria, suprimento e fechamento;
- auditoria, outbox, idempotência e correlation IDs;
- Capability Mesh com registry, dependências, entitlements e overrides;
- Console Owner com ficha, lifecycle, estruturas, contrato e observabilidade inicial.

### 4.2 Fundação segura, porém ainda grosseira

- RBAC por papel, método e família de rota: seguro por negação, mas sem grants granulares;
- escolha de contexto no frontend: usa a primeira opção autorizada em vez de seleção explícita;
- APIs de leitura: funcionais para protótipo, mas sem paginação/projeções operacionais;
- frontend: Gestão, POS e estados de UI estão concentrados em um contexto único;
- dashboards: parte das métricas ainda é agregada no navegador.

### 4.3 Domínios ainda não construídos

- roles customizáveis e permission grants;
- catálogo Food Service completo;
- Order e OrderItem operacionais;
- mesas, comandas e ondas de lançamento;
- production routing, tickets e KDS;
- transferências de mesa/comanda/item;
- recebíveis, acordos e renegociação;
- Order Hub e adapters externos;
- BI multi-site com projeções e drill-down.

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
├── orders            pedidos, itens, canais e fulfillment
├── table_service     mesas, comandas, junções e transferências
├── production        routing, tickets, filas e KDS
├── sales             fechamento comercial e snapshots
├── payments          recebimentos, split, estorno e conciliação
├── receivables       crediário, parcelas, liquidações e acordos
├── cash              sessões e livro razão do caixa
├── fiscal            documentos e eventos fiscais
├── reporting         projeções, métricas e drill-down
├── integrations      TEF, PIX, fiscal, delivery e device bridge
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
    ├── payments
    ├── receivables
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

Order
├── ServiceTable opcional
├── Customer opcional
├── OrderItem
│   ├── ModifierSnapshot
│   ├── lançamento/ator/horário
│   └── ProductionState
├── ProductionTicket
└── TransferHistory

Sale
├── Order(s) de origem
├── SaleItem snapshots
├── Payment(s)
├── Receivable(s)
└── FiscalDocument(s)
```

Invariantes:

1. item transferido nunca desaparece; gera origem, destino, ator, motivo e horário;
2. produção não altera preço ou total financeiro;
3. pagamento confirmado nunca excede o saldo devido sem regra explícita de troco;
4. venda só fica `PAID` quando os meios confirmados + saldo convertido em recebível cobrem o devido;
5. recebível não altera silenciosamente o documento original;
6. caixa esperado vem exclusivamente do ledger;
7. capability e permission são avaliadas no servidor;
8. toda transição crítica é auditável e idempotente quando repetível.

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

- `ServiceTable` com `FREE`, `OPEN`, `WAITING`, `PAYMENT`, `CLOSED`;
- abertura de mesa ou comanda individual;
- lançamento incremental e conta consolidada;
- vínculo de cliente e atendente;
- concorrência otimista/pessimista definida por comando;
- histórico operacional.

Gate:

- abrir mesa → lançar → adicionar depois → consultar total consolidado;
- dois operadores não sobrescrevem consumo silenciosamente.

### S8 — Production Routing e KDS

Objetivo: encaminhar itens ao ponto correto de produção.

Entregas:

- production points: cozinha, bar, copa e impressora;
- regras de roteamento por produto/modifier/store;
- `ProductionTicket` e itens;
- estados `NEW`, `ACCEPTED`, `PREPARING`, `READY`, `DELIVERED`, `CANCELLED`;
- tela `/kds` com tempo, prioridade e concorrência;
- fallback de impressão quando contratado.

Gate:

- item enviado aparece uma única vez no destino correto;
- KDS indisponível não corrompe o order;
- transições são auditadas.

### S9 — Transferências e Comandas Avançadas

Objetivo: suportar movimentações reais sem perda de rastreabilidade.

Entregas:

- mesa → mesa;
- comanda → comanda;
- item → mesa/comanda;
- juntar e separar mesas;
- motivo, ator, origem, destino e reversão permitida;
- proteção contra transferência durante fechamento incompatível.

Gate:

- total e quantidade são conservados;
- histórico reconstrói a trajetória de cada item;
- testes cobrem transferências concorrentes.

### S10 — Payment Engine 2.0

Objetivo: completar a experiência financeira preservando o motor existente.

Entregas:

- dinheiro, PIX, débito, crédito, vale refeição/alimentação, crédito da loja e conta;
- split por valor, pessoa ou itens quando aplicável;
- troco calculado no servidor;
- pagamento parcial e retomada;
- estorno/refund com permission;
- adapters de provider e conciliação;
- providers falsos restritos a teste.

Gate:

- `PAID` somente com cobertura integral confirmada;
- dois pagamentos simultâneos não ultrapassam o devido;
- confirmação repetida é idempotente.

### S11 — Crediário e Receivables

Objetivo: converter saldo autorizado em obrigação financeira rastreável.

Entregas:

- customer pessoa/empresa;
- limite e autorização de conta;
- `Receivable` com original, pago, saldo, emissão, vencimento, status e sale;
- lançamento de saldo restante em conta;
- eventos e auditoria financeira.

Gate:

- recebível aparece imediatamente no Gestão;
- venda e recebível são atômicos;
- saldo não desaparece nem é duplicado.

### S12 — Recebimentos e Renegociação

Objetivo: cobrar e renegociar sem alterar silenciosamente a origem.

Entregas:

- seleção de um ou vários recebíveis;
- liquidação total/parcial e split;
- juros, multa e desconto autorizados;
- `Agreement/Renegotiation` com parcelas e vínculos originais;
- aging e vencidos.

Gate:

- toda mudança financeira possui ator, permission, motivo e trilha;
- documentos originais permanecem imutáveis.

### S13 — Cash Operations

Objetivo: completar o caixa físico sobre o ledger já existente.

Entregas:

- estados `CLOSED`, `OPEN`, `CLOSING`, `CLOSED`;
- opening, sale payment, bleed, reinforcement, refund e closing;
- conferência cega opcional;
- histórico, saldo esperado e divergência;
- vínculo com terminal e operador.

Gate:

- saldo esperado deriva exclusivamente do ledger;
- fechamento concorrente é protegido;
- divergência nunca é recalculada apenas no frontend.

### S14 — Order Hub e Delivery Foundation

Objetivo: unificar origens sobre o Order já existente.

Entregas:

- balcão, mesa, retirada e delivery no mesmo hub;
- canais e fulfillment normalizados;
- adapter contract para iFood, 99, WhatsApp e e-commerce;
- reconciliação, retries e idempotência externa;
- nenhuma integração externa no caminho crítico local.

Gate:

- order não depende de nascer em um terminal físico;
- falha de canal não duplica pedido.

### S15 — Business Intelligence V1

Objetivo: transformar eventos em gestão multi-site.

Entregas:

- projeções server-side por período;
- faturamento, vendas, ticket, recebimentos e caixa;
- mesas, produção, cancelamentos e descontos;
- produtos, estoque e ruptura;
- recebíveis e formas de pagamento;
- filtros organização → região futura → store → terminal → operador;
- drill-down e rastreabilidade.

Gate:

- toda métrica possui fonte persistida conhecida;
- dashboards não carregam históricos inteiros no browser.

### S16 — Dashem Control Completion

Objetivo: concluir o plano de controle sem invadir a gestão do tenant.

Entregas:

- leads e conversão;
- contratos, limites, capabilities e onboarding;
- entrega e lifecycle do administrador contratual;
- timeline de identidade e e-mail sem tokens;
- saúde de Auth, API, banco, outbox, workers, fiscal e integrações;
- suporte assistido temporário;
- incidentes, auditoria e erros recentes;
- Resend com domínio, SPF, DKIM, DMARC e webhooks.

Gate:

- cliente opera sem acessar o Control;
- Control não cria equipe cotidiana;
- suporte possui motivo, prazo e auditoria.

### S17 — Capability Profiles

Objetivo: compor verticais sem forks.

Entregas:

- profiles `FOOD_SERVICE`, `RETAIL`, `GROCERY` futuros;
- bundles versionados e persistidos;
- configuração e dependências por tenant/store/terminal;
- contribution points de UI por capability;
- migração segura de versão de contrato.

Gate:

- vertical é composição de módulos, não branch de código;
- desativar capability remove disponibilidade sem apagar histórico.

### S18 — Operational Hardening

Objetivo: preparar piloto real.

Entregas:

- concorrência de mesa, order, pagamento, transferência e fechamento;
- retries e idempotência de comandos críticos;
- matriz tenant/store/permission/capability;
- rate limit e proteção de sessão;
- testes de conectividade degradada e recuperação;
- observabilidade, alertas e runbooks;
- backup/restore e rollback de migration exercitados.

Gate:

- suíte crítica automatizada verde;
- nenhuma falha conhecida pode perder operação silenciosamente.

### S19 — Piloto Comercial

Objetivo: validar trabalho real em uma operação pequena.

Perfil:

- 1 estabelecimento;
- 1–3 caixas;
- 5–15 funcionários;
- balcão + mesas + cozinha;
- PIX, cartão e dinheiro.

Medir:

- tempo e cliques por tarefa;
- tempo até produção e entrega;
- pagamento e fechamento;
- erros, cancelamentos, transferências e divergências;
- estabilidade e recuperação;
- percepção de velocidade e clareza.

Gate:

- decisões baseadas em operação observada, não somente opinião visual.

## 8. Dependências e ordem de execução

```text
S0
└── S1
    └── S2
        ├── S3
        │   └── S4
        │       └── S5
        │           └── S6
        │               └── S7
        │                   └── S8
        │                       └── S9
        └───────────────────────────┐
                                    └── S10 → S11 → S12 → S13

S6 → S14
S3 + S4 + S7 + S10 + S11 + S13 → S15
S0–S15 + S16 + S17 → S18 → S19
```

S16 pode evoluir em paralelo, mas não pode mudar silenciosamente contratos do
Commerce Plane. S17 consolida profiles após capabilities reais possuírem
implementações, evitando bundles apenas cosméticos.

## 9. Registro de dívidas atuais a eliminar

| Dívida atual | Sprint responsável | Resultado obrigatório |
|---|---|---|
| Gestão e POS alternados por estado global | S1 | rotas e shells independentes |
| Diagnóstico técnico dentro do Gestão | S1 | somente no Control |
| Um contexto concentra todos os domínios | S1 | contextos/queries por domínio |
| Primeiro tenant/store/register selecionado | S2 | contexto explícito |
| RBAC por rota/papel | S2 | permission grants granulares |
| Control convida qualquer papel interno | S2 | somente admin contratual + segurança |
| Produtos, preços e saldos consultados separadamente com N+1 de saldo | S4 | `SellableProduct` paginado |
| Primeiros seis produtos tratados como favoritos | S4 | favoritos persistidos |
| Estoque baixo visual fixado em 5 | S4 | `minimum_stock` real |
| Categoria inferida da descrição | S4 | relacionamento real |
| Listagens sem paginação | S4/S15 | paginação/cursor server-side |
| BI agregado no browser | S3/S15 | read models do backend |
| Poucos testes frontend de fluxos | S0 e contínuo | testes por shell e domínio |
| Endpoint de identidade excessivamente amplo | S1/S2/S16 | routers por responsabilidade |

## 10. Política de execução

Antes de iniciar uma sprint:

1. confirmar dependências concluídas;
2. escrever casos de aceite e invariantes;
3. mapear migrations e policies RLS;
4. definir permissions e capabilities aplicáveis;
5. definir eventos/auditoria;
6. listar estados de loading, vazio, erro, retry e conflito.

Durante a sprint:

1. backend e frontend evoluem pelo mesmo contrato;
2. nenhuma UI antecede indefinidamente persistência e permission;
3. nenhuma mutação crítica nasce sem teste negativo;
4. mudanças estruturais possuem migration e rollback;
5. métricas não são inventadas para preencher espaço.

Ao concluir:

1. gate automatizado verde;
2. fluxo manual validado com dados reais de teste;
3. documentação e README atualizados;
4. CI e deployment observados;
5. dívida residual explicitamente registrada.

## 11. Próximo passo autorizado por este roadmap

O próximo ciclo de implementação deve ser:

```text
S0 — Baseline, contratos e testes de caracterização
```

Somente depois do gate de S0 deve começar o refactoring estrutural de S1. Isso
preserva o core já correto e impede que a nova experiência do cliente seja
construída sobre responsabilidades ambíguas.
