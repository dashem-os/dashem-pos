# Roadmap Canônico V2 — Dashem Commerce OS / Dashem POS

Status: **diretriz canônica para a próxima fase de construção**  
Data: 23 de agosto de 2026  
Revisão: **Gate B `PASSED` em 04/09/2026 — Operational Acceptance concluída com
OA-4 `14/14` contra o deploy publicado. O pré-piloto S21 permanece `NO-GO`,
agora por Gate C, Gate D e homologações externas, não mais por Gate B.**
Substitui como referência de execução qualquer sequência anterior que conflite com este documento.

Atualização corretiva de 1º de setembro de 2026: o Dashem Control está
funcionalmente suficiente para avançar à arquitetura de informação da Gestão,
mas não está declarado completo para produção. A execução imediata está
detalhada nos Sprints corretivos 5.2–5.4 de
[`tenant-management-correction-sprints.md`](tenant-management-correction-sprints.md).
Essa trilha não renumera nem substitui os Sprints canônicos abaixo; o pré-piloto,
storage comercial e homologações externas preservam seus próprios gates.

Atualização de contrato de 5 de setembro de 2026: o **S25 — Liquidação
progressiva da comanda** foi contratado pelo dono do SaaS e escrito na seção 7.
Ele converte a `CheckoutNegotiation` de snapshot de fechamento em conta viva, com
projeção de settlement por item, identidade do pagador e segurança sob
concorrência entre terminais.

Atualização de estado de 5 de setembro de 2026: **S23 e S24 foram contratados,
construídos e dados por entregues no gate interno**, por decisão do dono do SaaS
depois de ver as duas na tela — vitrine com estado vazio honesto, cartão com
foto, um toque lançando no balcão, e o cadastro com upload próprio e biblioteca
DASHEM. Ajustes de acabamento ficam para depois e não reabrem os gates. Duas
correções de registro acompanham a promoção: o S23 entregou o balcão e **não** o
seletor compartilhado com a comanda, agora registrado como dívida própria na
seção 9; e o S9 deixou de ser `PARCIAL` por falta de tela — `PaymentProviderManager`
existe, está montado na Gestão e cobre provider, bridge TEF e vínculo de
maquininha. O S9 nunca foi o cadastro de produtos e sortimentos: esse é o S4,
estendido pelo Gate 5.4.0. Ainda em 05/09, e por pergunta do dono, apurou-se que
o **S9 jamais teve seção neste documento** — a seção 7 saltava de S8 para S10, e
o sprint era avaliado contra um contrato que morava só no ADR-022. A seção foi
escrita na posição dela, reconstruída a partir da evidência no repositório.

Atualização de estado de 4 de setembro de 2026: o **Gate B foi promovido para
`PASSED`** após a matriz OA-4 fechar `14/14` contra o deploy publicado, com o
cenário 14 reescrito durante a execução por decisão do dono do SaaS. A seção 9
recebeu os achados da homologação — cadastro de dispositivo genérico, totem
inexistente, reativação que não devolve o navegador e mesa sem turno — e o S21.1
foi corrigido pela nova regra de autoridade. A responsividade e o UI/UX seguem
em redesenho por outro agente.

Atualização de estado de 3 de setembro de 2026: os Gates 5.4.0–5.4.3 estão
publicados com CI verde; o Gate 5.4.4 foi aberto para vocabulário, conteúdo e
mídia por atividade; o OA-4 teve a primeira execução assistida no deploy, com
cinco cenários não credenciados aprovados e catorze credenciados ainda
pendentes. *(Superado pela atualização de 4 de setembro acima.)* As seções 4 e
9 abaixo receberam marcação de entregue, a refatorar e pendente; o texto da
seção 4 ainda descreve a leitura feita logo após o S7 e não foi reescrito.

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

Estado em 03/09/2026: **entregue, com uma entrega da lista em aberto desde o
sprint original**. Categoria, produto, preço, saldo, paginação, busca,
`SellableProduct`, acesso rápido, alertas de mínimo, modifiers e combos estão
implementados e protegidos por teste.

`imagem` constava como entrega deste sprint e nunca chegou à interface: o campo
`products.image_url` existia, nenhuma tela preenchia e nenhuma exibia. Em
03/09/2026 o cadastro passou a aceitar o endereço da imagem, a lista do catálogo
mostra miniatura e o cartão do PDV mostra a foto, com área reservada e fallback
pela inicial para a grade não desalinhar.

A refatorar no Gate 5.4.4: mídia continua sendo um endereço avulso. Falta a
biblioteca de imagens do sistema, o upload do acervo próprio do tenant e a
prova de isolamento entre inquilinos. Binário embutido no registro está
proibido. O upload gerenciado depende do limite de storage no contrato.

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

Estado: **concluído no gate interno em 04/09/2026** ([auditoria de confronto](../quality/sprint-confrontation-audit-2026-09-04.md)).
O núcleo já existia; a metade que faltava — a tela — foi entregue no mesmo dia.
`PaymentProviderManager` cadastra e reconfigura provedores, pareia bridge com
telemetria, vincula maquininha a um caixa e pausa, reativa ou revoga o vínculo,
com SmartPOS explicitamente marcado como cadastro sem execução. Navegação por
contribuição sob a capability `tef` e `provider.read`, escritas sob
`provider.configure` (migração `072`).

Duas ressalvas: o **Gate C continua `OPEN`** — entregar a tela não prova a
cadeia de execução —, e a aceitação de interface
(`frontend/e2e/payment_providers/`) **roda apenas à mão**, contra a API local.
Ela provou a entrega e não é protegida pelo CI: se a tela regredir, nada avisa.
O gate externo de homologação de cada provider permanece independente.

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

### S9 — Payment Providers e Dashem TEF Bridge

Estado: **concluído no gate interno; homologação externa aberta.** Esta seção foi
escrita em 05/09/2026, **reconstruída a partir da evidência no repositório**, e
não transcreve um contrato original: o S9 foi construído inteiro e nunca teve
seção própria neste documento — a seção 7 saltava de S8 para S10. A ausência teve
custo: a auditoria de confronto de 04/09 avaliou o sprint sem ter a lista de
entregas na mão, e o próprio dono do SaaS perguntou, em 05/09, onde o S9 estava.
Onde o [ADR-022](../architecture/adr-022-payment-device-binding.md) é explícito,
o texto abaixo o cita; onde não é, descreve o que o código faz, sem atribuir
intenção que não esteja registrada.

Objetivo: acoplar provider de pagamento e pinpad à venda sem que a regra de
negócio dependa de qual adapter está instalado, e sem que o navegador escolha por
onde o dinheiro passa.

Contrato que o governa: ADR-022 (Gate C, aceito em 24/08/2026, `PASSED` em
04/09/2026) e ADR-023 (Gate D, `PASSED` em 04/09/2026). Os oito critérios de
aceite do ADR-022 são o gate deste sprint e não são repetidos aqui.

Entregas, como existem em `app/models/provider.py` e `/api/v1/providers`:

- `PaymentProviderConfiguration` — provider por unidade, com versão de adapter,
  referência segura de credencial e timeout, único por `(tenant, store,
  provider_code)`. Credencial é referência, nunca segredo em claro;
- `TefBridgeTerminal` — bridge pareado a um caixa, com segredo de pareamento
  guardado como hash, versão de protocolo, heartbeat, último erro e estado
  `UNPAIRED → ONLINE → OFFLINE → DEGRADED`. Um caixa tem no máximo um bridge;
- `PaymentDeviceBinding` — a rota autoritativa de um POS até a execução de
  cartão, única por dispositivo operacional. Guarda caixa, dispositivo, provider,
  modo de execução e, para TEF, o terminal pareado. Pausa e revogação registram
  motivo;
- `ProviderTransaction` e `ProviderTransactionEvent` — a transação no provider e
  a sua trilha, com o vínculo usado preservado;
- `PaymentExecutionEvent` — os quatro estágios `REQUESTED → APPROVED → EXECUTED
  → RESULT_RECORDED` como fatos append-only, base do Gate D;
- `OperationalProductivityProjection` — produtividade por sessão operacional,
  reconstruível a partir dos fatos, com fórmulas publicadas;
- onze rotas: configuração, vínculo com alteração de estado, pareamento e
  heartbeat de bridge, execução, reconciliação e o callback pelo qual o bridge
  reporta o resultado sob o próprio principal;
- `provider_service._resolve_execution_binding`, que recompõe e revalida a cadeia
  tenant → unidade → caixa → POS → provider → modo de execução na mesma
  transação da execução;
- `PaymentProviderManager` na Gestão, guardado pela capability `tef` e pela
  permission `provider.read`, onde o lojista cadastra provider, pareia bridge,
  cria vínculo de maquininha e pausa ou revoga — **entregue em 05/09/2026**, e é
  a peça que faltava para o sprint deixar de ser `PARCIAL` pela régua da seção
  10.

O que este sprint deliberadamente **não** entrega:

- **SmartPOS executável.** `SMARTPOS` é modo de vínculo, não promessa de
  integração: sem adapter homologado a execução é recusada com 409 explícito, e
  a própria tela diz isso. Nunca cai em cartão manual nem simula aprovação. A
  superfície de operação do SmartPOS é assunto do S22, que não está autorizado;
- **homologação de provider.** É contrato, credencial e certificação de
  terceiro, permanece um gate externo e é uma das razões de o S21 seguir `NO-GO`;
- **hardware do Print Bridge**, que é do S21.1 e não deste sprint.

Prova, além dos oito critérios do ADR-022:

- `tests/test_s9_payment_providers.py` — cobre os critérios 1, 4 e 5: payload
  legado que escolhe provider e terminal é recusado com 422; bridge offline não
  bloqueia dinheiro, PIX nem outra parcela; SmartPOS recusado com 409;
- `tests/test_gate_c_payment_device_binding.py` — a matriz de cruzamento que
  faltava: vínculo do tenant vizinho recusado nos dois sentidos, vínculo pausado
  que deixa de executar e volta ao ser reativado, POS revogado que órfã o
  vínculo, e o turno PIN que só executa pelo seu próprio POS;
- `tests/test_gate_d_payment_audit.py` e `tests/test_gate_d_audit_completeness.py`
  — imutabilidade da trilha e ausência de fato duplicado por resultado repetido.

### S10 — Dashem Channel Hub e External Order Inbox

Estado: **concluído no gate interno** ([auditoria de confronto de 04/09/2026](../quality/sprint-confrontation-audit-2026-09-04.md)). Modelos, serviço, endpoint, teste e `ChannelHubWorkspace` consumindo. O gate externo de certificação de canal permanece independente.

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

Estado: **concluído no gate interno** ([auditoria de confronto de 04/09/2026](../quality/sprint-confrontation-audit-2026-09-04.md)). `/kds` real, roteamento configurável e dispatch idempotente. O fallback de impressão depende do Print Bridge, ainda no S21.1.

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

Estado: **concluído no gate interno em 04/09/2026**. A operação move quantidade
de item, comanda inteira ou atendimento inteiro; separa um grupo diretamente
para mesa livre e une duas sessões ativas. A linhagem aparece na tela e conserva
Order, OrderItem, produção, versões, ator, motivo, auditoria e outbox. O checkout
por Order permite pagamento individual ou por grupo, inclusive em parcelas,
sem encerrar as demais comandas da mesa.

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

Estado: **entregue no gate interno em 05/09/2026**, superando o `PARCIAL` da
[auditoria de confronto de 04/09/2026](../quality/sprint-confrontation-audit-2026-09-04.md).
A janela ganhou maçaneta: `ChannelHubWorkspace` cadastra oferta por canal,
vincula o código do item no merchant, envia o lote de publicação, importa o
documento de repasse e registra o pagamento recebido. A projeção passou a ser
resolvida no servidor — nome e SKU do produto, provider e merchant da conexão,
itens do lote e pagamentos do documento viajam com a linha, de modo que a tela
nunca renderiza um identificador nem junta duas listas no navegador para achar
um nome.

Uma porta continua fechada **de propósito, e não por falta de tela**: o
resultado item a item da publicação (`POST /publications/{batch_id}/results`) é
a palavra do adapter. Um botão para ele deixaria uma pessoa assinar a resposta
do marketplace, e todo lote leria verde sem o canal jamais ter sido chamado.
Enquanto nenhum provider estiver homologado, o lote fica **pendente** e a tela
diz isso com todas as letras. O mesmo vale para a mensagem outbound do canal,
que pertence ao worker.

O gate externo de certificação de canal permanece independente e continua
aberto.

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

Estado: **concluído no gate interno em 04/09/2026**. A Gestão cria, edita,
ordena e arquiva ambientes e mesas com motivo auditável; a identidade por código
é preservada e a versão da mesa protege alterações concorrentes. A movimentação
de clientes e comandas continua pertencendo ao fluxo operacional do S12.

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

Estado: **concluído no gate interno**. O recebimento possui comando idempotente,
allocation por título, forma, provider, ator, motivo e ajustes explícitos. A
liquidação parcial atualiza somente a projeção de saldo e acrescenta ledger; o
principal original permanece imutável. Acordos bloqueiam os títulos de origem
como `RENEGOTIATED` e emitem parcelas-filhas ligadas ao acordo, de modo que cada
parcela possa ser recebida ou falhar independentemente. Eventos de cobrança e
promessa possuem trilha própria. Dinheiro exige sessão de caixa aberta e gera
um único movimento `RECEIVABLE_PAYMENT`; outros meios não alteram numerário.

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

Estado: **concluído no gate interno** ([auditoria de confronto de 04/09/2026](../quality/sprint-confrontation-audit-2026-09-04.md)). `BiDailyFact` e `BiProjectionState` com `DashboardBI` consumindo; estado vazio real observado em produção em 04/09.

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

Implementação concluída:

- `BiDailyFact` mantém fatos diários descartáveis por tenant, unidade, escopo e
  dimensões operacionais; o core transacional continua sendo a autoridade;
- `BiProjectionState` publica versão, watermark, competência, status e instante
  da última projeção, tornando atraso e falha observáveis;
- a reconstrução substitui somente o intervalo solicitado e é idempotente em
  relação aos fatos de origem, sem alterar vendas, pagamentos ou recebíveis;
- a API entrega filtros por unidade, terminal, operador e canal, fórmulas
  versionadas e drill-down paginado até a fonte persistida;
- a Gestão consome apenas o read model agregado, exibe o atraso e não reduz o
  histórico transacional no browser;
- RLS, permissions `bi.read`/`bi.refresh`, rebuild, isolamento entre tenants e
  estabilidade dos totais são cobertos por testes automatizados;
- a decisão de autoridade, atualização e descarte está registrada no ADR-011.

### S17.1 — Identidade Operacional e Correção da Jornada

Estado histórico: **implementação interna concluída, aceite de jornada
reaberto pelo ADR-024**. O backend preserva parte da fundação, mas “PIN” deixa
de nomear sozinho a identidade: o contrato passa a ser código + PIN pessoal +
função + escopo + terminal + sessão operacional.

Entregas:

- administradores e gerentes entram por e-mail e permanecem na Gestão;
- supervisor, caixa e atendente são cadastrados sem e-mail fictício, com unidade,
  código de colaborador e PIN individual;
- portão de PIN obrigatório ao assumir PDV ou Mesas em terminal autorizado;
- token operacional curto e assinado, limitado a tenant, unidade, terminal,
  membership e papel;
- hash forte, salt individual, bloqueio temporário por tentativas e redefinição
  auditável de PIN;
- `SUPERVISOR` substitui `AUDITOR` nas memberships e interfaces do tenant;
- reserva real continua em `RESERVED`; motivo de bloqueio não pode mais fingir
  ser reserva;
- registros legados cujo bloqueio dizia “Reservado” aparecem como reserva e
  oferecem “Cliente chegou · abrir mesa”, corrigindo o estado e iniciando a
  sessão em uma única jornada;
- catálogo persistido pode ser arquivado pela Gestão sem apagar vendas, estoque
  ou trilha histórica; o PDV deixa de oferecer o item arquivado.

Gate:

- operador sem e-mail autentica com código e PIN e recebe somente o escopo da
  unidade e do terminal selecionados;
- PIN incorreto não emite token e cinco erros bloqueiam temporariamente;
- membership, usuário, tenant, unidade ou terminal inativos impedem ativação;
- administrador não é redirecionado automaticamente para o PDV;
- a Gestão não define nem conhece o PIN definitivo do colaborador;
- mesa reservada possui ação de chegada, enquanto mesa bloqueada exige motivo de
  impedimento;
- frontend, backend, migração completa, downgrade/upgrade e testes de isolamento
  permanecem verdes.

Decisão registrada no
[`ADR-012`](../architecture/adr-012-operational-pin-identity.md).

### S17.2 — Jornada Gerencial e Cadastro Funcional

Estado histórico: **implementado, mas parcialmente substituído pelo ADR-024**.
A separação da ficha funcional permanece válida; a entrada gerencial direta em
mutações do PDV e a definição administrativa do PIN foram revogadas.

Entregas:

- administrador, responsável do tenant e gerente autenticados por e-mail entram
  na Gestão e podem abrir a superfície do terminal, mas uma operação humana
  exige assunção por colaborador;
- o PIN permanece exclusivo da assunção de turno por supervisor, caixa e
  atendente e desaparece imediatamente após autenticação válida;
- `/identity/me` resolve a membership operacional dentro do tenant e da unidade
  assinados no token antes de consultar tabelas protegidas por RLS;
- `Employee` separa a ficha completa do funcionário de memberships e
  credenciais;
- a Gestão permite buscar funcionário existente ou concluir novo cadastro antes
  de conceder código, função, escopo e ativação temporária; o funcionário define
  o próprio PIN;
- cadastro funcional pode ser consultado e editado sem apagar histórico de
  acessos ou operações;
- toast passa a respeitar a largura da viewport e mantém apresentação compacta
  em telas pequenas.

Gate:

- clicar em **Validar no PDV** com perfil gerencial abre a superfície do
  terminal com a identidade administrativa real, sem exigir que o gestor se
  apresente como atendente;
- a validação gerencial não cria turno nem produtividade operacional, mas toda
  mutação executada continua real, autorizada e auditada pelo servidor;
- ativação por código + PIN não recarrega a aplicação, não cai em falso estado
  de acesso pendente e não abre seletor organizacional;
- funcionário e credencial possuem persistência, autorização e auditoria
  independentes;
- migrations, contratos, frontend e testes de regressão permanecem verdes.

Decisões registradas nos
[`ADR-012`](../architecture/adr-012-operational-pin-identity.md) e
[`ADR-013`](../architecture/adr-013-employee-access-boundary.md).

### S17.3 — Ativação de Terminal e Entrada Operacional Pública

Estado: **REPROVADO NA JORNADA REAL; absorvido pelo plano OA-1–OA-4**. O CI
protegeu componentes isolados e chegou a exigir um atalho operacional no login
gerencial, contrariando o ADR-014. A validação no deploy também demonstrou que,
após código + PIN válidos, o POS voltava a procurar tenant da pessoa.

Entregas:

- `/operate` é uma superfície dedicada do terminal e não é anunciada pelo login
  administrativo;
- código e PIN não formam um login global: a troca somente ocorre em navegador
  previamente autorizado por administrador ou gerente;
- a Gestão autoriza um `OperationalDevice` POS ativo e o backend assina tenant,
  unidade, caixa e dispositivo em credencial de infraestrutura persistida no
  navegador;
- o endpoint público deriva todo o escopo da credencial assinada e nunca aceita
  tenant, unidade ou caixa escolhidos pelo operador;
- pausa, revogação, troca de vínculo ou desativação do caixa invalida novas
  entradas imediatamente;
- a identidade operacional continua curta, individual e armazenada apenas na
  sessão; ao sair do turno, o terminal permanece autorizado para a próxima
  pessoa;
- o acesso por e-mail continua sendo a entrada de administradores e gerentes,
  que podem autorizar e abrir a superfície do PDV sem substituir a pessoa que
  assume a operação.

Gate:

- sem autorização de terminal, `/operate` não oferece tentativa de PIN;
- token de terminal adulterado, expirado, pausado, revogado ou fora do vínculo é
  rejeitado antes da consulta à credencial do funcionário;
- PIN válido em terminal autorizado emite token operacional limitado ao mesmo
  tenant, unidade e caixa;
- nenhum gate de contexto organizacional é exibido após a autenticação;
- frontend, backend, contratos e testes de isolamento permanecem verdes.

Decisões registradas no
[`ADR-014`](../architecture/adr-014-terminal-authorization.md) e no corretivo
[`ADR-024`](../architecture/adr-024-operational-employee-access.md). A execução
está em
[`operational-access-hardening-plan.md`](operational-access-hardening-plan.md).

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

Estado: **concluído no gate interno**. O Control possui contratos comerciais
versionados amarrados aos entitlements vigentes, checkpoints de onboarding com
evidência, timeline de entrega sem tokens, suporte temporário com escopo,
aprovação e expiração, incidentes sanitizados e visão operacional por tenant.
Componentes sem heartbeat são projetados como `UNINSTRUMENTED`. O Resend
permanece um gate externo desativado até existir domínio próprio validado; o
transporte temporário não é representado como infraestrutura pronta.

### S18.1 — Owner Financeiro SaaS e minimização operacional

Estado em 29 de agosto de 2026: Fases 0 a 4 concluídas no escopo persistido.
Além da fronteira, contratos, limites e faturamento SaaS, o Control possui agora
pagamentos, alocações, estornos, vencimentos e eventos de cobrança reais, com
RLS, AAL2, idempotência, auditoria/outbox e webhook HMAC fail-closed. Provider
comercial e transporte externo ainda não foram escolhidos e permanecem
desativados, sem adapter ou sucesso simulado. A Fase 4 materializa projeções
diárias reconstruíveis com fórmula, watermark, fingerprint e drill-down.

Objetivo: administrar a receita recorrente e a cobrança da própria Dashem sem
usar o Control como janela para a operação comercial ou financeira dos tenants.

Entregas:

- retirada de usuários ativos, unidades em operação, caixas, vendas,
  faturamento, estoque e quadro de funcionários das métricas do Control;
- conta de cobrança, assinatura, faturas e itens SaaS com snapshot contratual;
- pagamentos, alocações, estornos e conciliação exclusivos da receita Dashem;
- inadimplência, régua de cobrança e alterações manuais auditadas;
- MRR, ARR, movimentos de MRR, churn e recebimentos com fórmulas rastreáveis;
- permissões financeiras, AAL2, idempotência, auditoria e outbox;
- observabilidade técnica separada de indicadores comerciais e financeiros.

Gate:

- Control não consulta nem exibe dados operacionais ou financeiros dos tenants;
- Gestão continua sendo a única superfície das métricas do estabelecimento;
- fatura emitida e pagamento confirmado são preservados como fatos imutáveis;
- retry não duplica fatura, cobrança, pagamento ou alocação;
- todo indicador financeiro chega aos contratos e faturas SaaS de origem;
- nenhum cálculo depende de `Sale`, `CashSession`, pagamentos do PDV ou BI do
  tenant.

Estado: **Fases 0 a 4 concluídas no escopo interno**. Contratos, contas de
cobrança, faturas, recebimentos, estornos, saldo vencido e ações de cobrança são
fatos platform-owned rastreáveis. MRR, ARR, novo, expansão, contração, churn,
taxas e históricos são projeções reconstruíveis `SAAS_FINANCE_V1`; o primeiro
dia permanece baseline explícito, sem movimento zero fictício. Restam somente
gates externos de provider comercial, fiscal e transporte de cobrança, que não
são simulados. A especificação funcional e técnica está em
[`owner-financeiro-saas.md`](owner-financeiro-saas.md).

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

Estado: **concluído no gate interno**. Revisões de perfil, itens, atribuições e
contribution points são persistidos. `FOOD_SERVICE` e `RETAIL` estão ativos;
`GROCERY` permanece `DRAFT` enquanto depender de capacidades ainda não
implementadas. O backend impede o Owner de ativar uma capability inexistente,
resolve dependências e entrega navegação/health/reporting somente após cruzar
entitlement e permission. Desativação preserva linhas e histórico. O frontend
não decide mais quais módulos estão disponíveis: mantém apenas o registro local
das implementações visuais que consegue montar.

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

Estado: **concluído no gate interno**. Cada release recebe uma execução de
hardening com nove evidências mensuráveis; resultados genéricos não promovem o
gate. RPO/RTO são parte do contrato, respostas de API não são cacheadas e IDs de
correlação são sanitizados. O CI passou a restaurar um dump em banco novo e
verificar transação sentinela + revisão Alembic. O runbook estabelece que falha
externa isola a capability e que SEV1, perda/duplicidade ou quebra de isolamento
bloqueiam o piloto. A validação de campo continua pertencendo ao S21.

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

Estado: **NO-GO, mas o motivo mudou em 04/09/2026**. Nenhum gate corretivo
nosso barra mais o piloto: A, B, C e D estão `PASSED`. O que resta é externo —
homologação de provider e certificação de canal, que dependem de contrato,
credencial e hardware de terceiros — somado ao que este próprio sprint exige
abaixo. A instrumentação interna está implementada, mas a validação comercial em
campo não pode começar. O Control
persiste escopo, release de hardening, observações por
tarefa e gates de incidente. O dossiê só inicia após hardening `PASSED` e profile
`FOOD_SERVICE` ativo. TEF sem homologação e canal sem certificação são recusados.
Conclusão exige evidência de venda, produção, pagamento, transferência e
recuperação; SEV1/SEV2 bloqueia expansão. Nenhum cliente, hardware ou integração
externa foi inventado para marcar este gate como comercialmente concluído.

### S21.1 — Superfícies de acesso e identidades de dispositivo

Objetivo: remover da validação comercial qualquer ambiguidade entre pessoa,
terminal e periférico.

Entregas:

- novo login público, limpo e exclusivamente gerencial, por e-mail/OAuth, sem
  atalho para `/operate`;
- código e PIN restritos à superfície `/operate` de um terminal previamente
  autorizado, sem seleção de tenant ou unidade pelo colaborador;
- administrador e gerente autorizam e abrem a superfície do PDV; **revisto em
  04/09/2026** — na própria sessão web autenticada eles operam sob a própria
  identidade, e é no terminal de balcão compartilhado que código e PIN
  identificam quem assume o turno (ver a revisão do ADR-024);
- cadastro de **Clientes** na Gestão, com histórico comercial real;
- **Funcionários e acessos** como módulos visíveis e distintos: ficha funcional
  separada de convite por e-mail ou credencial operacional;
- terminais POS independentes de `kitchen_routing`; KDS, impressão e roteamento
  aparecem somente quando a capability está contratada;
- TEF como bridge pareado ao caixa, sem login humano na maquininha;
- especificação do Print Bridge para impressoras sem tela, com credencial de
  dispositivo, heartbeat, revogação e confirmação de trabalhos.

Gate:

- `/login` não contém entrada por PIN nem navega para `/operate`;
- `/operate` recusa código/PIN sem credencial válida de terminal;
- gestor autenticado abre a superfície do POS e, na própria sessão web, opera
  sob a própria identidade, rastreado e metrificado no seu perfil; no terminal
  compartilhado a assunção por código e PIN continua obrigatória para todos;
- ausência de `kitchen_routing` não quebra a gestão de terminais;
- Clientes e Funcionários aparecem somente por contribution, capability e
  permission efetivas;
- impressora não é declarada operacional antes do Print Bridge e do teste em
  hardware real.

Estado: **jornada de acesso concluída; identidade de periférico ainda não**.
Login, navegação gerencial, cadastros e autorização foram corrigidos pelo plano
OA-1–OA-4, cuja matriz fechou `14/14` contra o deploy publicado em 04/09/2026.
O que continua aberto nesta sprint é a metade dos **periféricos**: o protocolo
seguro do Print Bridge, a homologação externa de TEF e — levantado em 04/09 — o
fato de o cadastro de dispositivos ainda não distinguir ponto de operação,
navegador autorizado e periférico físico, declarando este último por texto livre
em vez de pareamento verificado. Totem e autoatendimento não pertencem a esta
sprint nem a nenhuma outra e precisam de decisão.

### S22 — Autoatendimento: totem e SmartPOS como superfície de operação

Proposto em 4 de setembro de 2026, ainda **não autorizado**. Existe para separar
duas coisas que hoje se confundem: o SmartPOS como *meio de execução de
pagamento* e o SmartPOS como *superfície onde a operação acontece*.

Contexto. `PaymentDeviceExecutionModeEnum.SMARTPOS` já existe e é, por decisão
do Gate C, apenas um modo de **cadastro**: a maquininha é o destino de uma
cobrança. Mas um SmartPOS de campo roda o próprio ponto de venda — catálogo,
comanda, fechamento — e um totem atende sem nenhuma pessoa da casa presente.
Nenhuma das duas é um "POS com tela menor": a primeira executa o pagamento
localmente em vez de atravessar um bridge; a segunda **não tem sessão humana**,
o que a coloca fora de todo o modelo de autoridade construído até o Gate B.

Entregas previstas:

- SmartPOS como `OperationalDevice` do tipo POS com execução **local**, distinta
  de `TEF_BRIDGE`, sem login humano na maquininha e com adapter homologado;
- superfície de autoatendimento sem sessão operacional, cuja autoria é um
  **service actor** persistido pelo servidor, no mesmo contrato do Gate A;
- capability própria, para que um tenant sem autoatendimento contratado não veja
  a superfície nem os pontos de operação correspondentes;
- fluxo de pedido self-service produzindo `Order` sem operador humano, com
  pagamento obrigatório antes do envio à produção;
- conciliação entre o pedido do totem, a execução de pagamento e o ticket de
  produção, sem inventar um colaborador para carregar a autoria.

Dependências e por que não é agora:

- **Gate C** é pré-requisito duro. Um totem que não cobra não serve, e cobrar
  exige a cadeia de execução vinculada ao dispositivo provada;
- o S21 (piloto comercial) deve rodar antes: não se lança autoatendimento em um
  cliente cujo balcão ainda não foi validado em campo;
- a decisão sobre mesa e comanda sem turno de caixa (seção 9) precisa estar
  tomada, porque um totem opera exatamente nessa fronteira.

### S23 — Vitrine operacional e seleção de produto compartilhada

Estado: **entregue no gate interno em 05/09/2026, com uma entrega da lista em
aberto**. Contratado em 04/09 e construído em seguida: migração
`073_store_catalog_layout`, rotas `GET`/`PUT /catalog/layout` e
`/catalog/quick-access`, permissions `catalog.layout.manage` e
`catalog.layout.personalize` semeadas nos perfis, `ProductShowcase` com as duas
faixas e o modo explícito de personalizar, e `test_s23_store_catalog_layout.py`
cobrindo reorder atômico, versão esperada com **409**, produto duplicado,
produto arquivado e ordenação sem `catalog.update`. O dono observou a tela em
05/09: vitrine vazia anuncia a si mesma — "a vitrine desta unidade ainda não foi
montada" —, o cartão exibe a foto e um toque lança no balcão.

**O que continua aberto:** o seletor visual compartilhado com a comanda.
`ProductShowcase` é consumido apenas por `QuickProductGrid`, no PDV;
`TableServiceWorkspace` ainda lança item por um campo de identificador de
produto, chamando `addOrderItem` sem vitrine, foto nem busca. A metade "balcão"
da entrega está feita; a metade "mesa" não.

Existe para que a tela inicial da operação seja o que a casa realmente vende,
arrumado por quem conhece o movimento, e para que lançar um item seja um toque
em vez de uma busca.

Contexto. O acesso rápido existe, e é **só pessoal**: `QuickAccessProduct` tem
chave em `(tenant, store, membership, product)`, sem nenhuma ordem padrão da
unidade. O PDV abre em "Todos", não na vitrine. A mutação exige `catalog.update`,
de modo que um caixa só ordena os próprios botões se receber poder sobre o
catálogo inteiro. A rota grava **uma posição por vez** e recusa posição ocupada,
o que torna o arraste impossível de aplicar atomicamente. E a ordenação não
distingue contexto de venda nem atividade, então quem opera balcão e retirada
acumula posições ambíguas.

Entregas previstas:

- layout padrão da unidade com escopo `tenant + store + sales_context +
  business_activity`, cabeçalho versionado e ordenação exclusiva da gerência;
- `quick_access_products` passa a representar **somente** atalhos pessoais e
  ganha contexto de venda e atividade no escopo, com backfill declarado —
  `COUNTER` e a atividade primária da unidade para as linhas existentes — e
  downgrade que restaura o escopo anterior;
- permissions próprias `catalog.layout.manage` e `catalog.layout.personalize`,
  removendo a exigência de `catalog.update` para ordenar botões;
- reorder atômico que recebe o array inteiro de posições, com versão esperada,
  `SELECT FOR UPDATE` no cabeçalho, idempotência e auditoria; as uniques de
  **posição** das duas tabelas passam a `DEFERRABLE INITIALLY DEFERRED`,
  enquanto a unique de produto dentro do layout permanece imediata;
- renderização em duas faixas — "Meus atalhos" acima, "Vitrine da unidade"
  abaixo — sem repetir item que já está na vitrine;
- modo explícito "Personalizar vitrine" para o arraste, separado do toque de
  venda e da rolagem, dimensionado para toque;
- seletor visual de produto compartilhado entre PDV e comanda: vitrine, imagem,
  categorias e busca comuns, com o comando transacional específico de cada
  jornada — `addSaleItem` no balcão, `addOrderItem` na mesa;
- a faixa pessoal aparece somente enquanto a sessão operacional daquela pessoa
  estiver ativa; encerrada ou expirada, o catálogo pessoal e o cache
  correspondente são descartados junto do token.

Gate:

- operador comum ordena os próprios atalhos sem `catalog.update` e não consegue
  reordenar a vitrine da unidade;
- dois gerentes reordenando a mesma vitrine: um vence, o outro recebe **409**
  com a versão esperada, **nunca 500** — inclusive quando a unique deferida
  estoura no `COMMIT` em vez do statement;
- o arraste aplica a lista inteira em uma transação; falha no meio não deixa
  posição parcial nem furo de ordenação;
- terminal sem operador não exibe faixa pessoal alguma; encerrada a sessão, a
  faixa e o cache somem antes da próxima identificação, e a mesma pessoa
  reentrando reencontra a própria faixa;
- produto arquivado ou indisponível não aparece em nenhuma das duas faixas;
- personalizar não desloca a vitrine: as posições da unidade permanecem as
  mesmas para quem tem atalhos e para quem não tem;
- um clique lança no balcão e na comanda pelo mesmo componente, com comando
  distinto por jornada;
- migration com upgrade, downgrade e backfill declarado; frontend, backend e
  drift check verdes.

Não depende do Storage: entrega com a `image_url` já cadastrada quando houver e
com o fallback pela inicial quando não houver. O seletor compartilhado é também
o que o SmartPOS do S22 poderá consumir sem reescrever catálogo.

### S24 — Mídia de produto e biblioteca DASHEM

Estado: **entregue no gate interno em 05/09/2026**. Contratado em 04/09 e
construído em seguida: migração `074_product_media` com
`primary_media_asset_id`, `media_assets` e `platform_media_assets`;
`media_service.resolve_product_images` resolvendo N imagens em uma chamada, com
TTL por propósito (`CATALOG_MEDIA_SIGNED_URL_TTL_SECONDS=21600`); biblioteca
DASHEM pesquisável e de escrita exclusiva da plataforma; upload privado
integrado ao cadastro por `ProductMediaPicker`. Os testes de
`test_s24_product_media.py` provam os quatro pontos duros do gate: foto de um
tenant invisível ao vizinho **e à plataforma**, biblioteca como prateleira e
nunca fallback, TTL escolhido pelo propósito e não pelo chamador, e localizador
forjado que não alcança arquivo alheio. A política de RLS de `media_assets` foi
escrita sem a cláusula `app.platform_access`, como o contrato exige.

Observado pelo dono em 05/09: o cartão do PDV e o cadastro exibem a foto, e o
editor oferece "Enviar minha foto", "Escolher da biblioteca" e remoção, com o
aviso de que a biblioteca não consome cota. Ajustes pontuais de acabamento
ficam para depois e não reabrem o gate.

Fecha a dívida de imagem que o S4 declarou como entrega e nunca levou à
interface, antes carregada na trilha corretiva 5.4.4.

Contexto. Em 03/09 o cadastro passou a aceitar o **endereço** da imagem, e é só
isso que existe: um campo de texto, duplicado na tela. O upload do tenant está
construído no servidor — namespace por tenant, validação de tipo, reserva de
quota e URL assinada — e nunca chegou a tela alguma; as três funções de storage
do cliente sequer enviam `X-Tenant-ID`, então falhariam com 400 se alguém as
chamasse. A biblioteca da plataforma está prevista formalmente e não existe. A
assinatura vale 60 segundos para tudo, o que serve a documento e não a vitrine.

Entregas previstas:

- `primary_media_asset_id` no produto, com `image_url` preservada como
  compatibilidade e nunca reescrita nem apagada;
- resolvedor determinístico: asset persistido → `image_url` legada → fallback
  pela inicial;
- projeção `sellable-products` entregando `image` com origem, URL assinada e
  `expires_at`, resolvida e agrupada no servidor — nunca uma assinatura por
  cartão;
- TTL por propósito, configurado no servidor e nunca escolhido pelo cliente:
  documento privado em 60 s, exportação entre 5 e 15 minutos, mídia de tenant em
  6 h por `CATALOG_MEDIA_SIGNED_URL_TTL_SECONDS=21600`, biblioteca DASHEM em 24 h
  ou cache por versão;
- biblioteca DASHEM versionada e pesquisável, com atividades sugeridas,
  categorias e tags semânticas, coleção genérica, escrita exclusiva da
  plataforma. **É camada de inspiração, não fallback**: o lojista escolhe uma
  imagem dela ou sobe a própria, e o produto passa a referenciar o que foi
  escolhido. O resolvedor nunca busca lá por conta própria;
- upload privado integrado ao cadastro, substituindo o campo de endereço e
  removendo o campo duplicado, com as três funções de storage do cliente
  corrigidas para enviar contexto de tenant;
- padrão de storage como valor explícito do plano, copiado para o contrato no
  provisionamento — nunca fallback invisível no momento do upload; tenants
  antigos sem quota recebem nova versão contratual pelo Owner.

Gate:

- tenant A nunca lê asset de tenant B, provado por teste que reprova se
  conseguir;
- **foto de tenant nunca entra na biblioteca da plataforma**, nem como sugestão,
  nem como referência, nem por curadoria: o fluxo é de mão única, da plataforma
  para quem quiser usar. Uma foto que o lojista subiu é dele e morre no
  namespace dele;
- **ninguém fora do tenant vê a foto, a DASHEM inclusive.** A consequência é
  dura e vale registrar: a política de RLS da tabela de mídia **não leva a
  cláusula `app.platform_access`** que as demais tabelas de tenant carregam.
  Copiar o padrão da casa aqui abriria a escotilha da plataforma sobre o acervo
  do lojista. O Owner continua medindo bytes para quota e cobrança, pelo que já
  existe em `storage_measurements` — medir tamanho não é ver arquivo, caminho
  nem miniatura, e nenhuma tela do Control lista asset de tenant;
- a mídia é do tenant e serve todas as suas unidades; o que muda por unidade é a
  ordem da vitrine, e por pessoa, a faixa de atalhos — a foto não ganha uma
  quarta dimensão de escopo;
- produto sem imagem escolhida cai na inicial, e **nunca** recebe uma foto da
  biblioteca por conta própria: o sistema não decide como o item do lojista se
  parece;
- escolher da biblioteca não consome storage do tenant, então um tenant sem
  contrato de storage tem vitrine com foto — só não sobe arquivo próprio;
- endereço cadastrado antes de 04/09 continua exibindo, e a migração para asset
  é gradual e reversível;
- a projeção resolve N imagens em uma chamada e o cartão não dispara assinatura
  própria; `expires_at` viaja em UTC sem offset, respeitando o guard de
  timestamp;
- upload recusado por ausência de contrato de storage responde com o motivo
  real, e a vitrine do S23 continua funcionando sem ele;
- homologação real com dois tenants, quota declarada e expiração observada;
- migration com upgrade, downgrade e drift check verdes.

O primeiro marco é a biblioteca, não o upload: ela dá foto a todo tenant sem
depender de entitlement comercial nem de arquivo do lojista.

### S25 — Liquidação progressiva da comanda (Live Settlement)

Contratado com o dono do SaaS em 5 de setembro de 2026, **não iniciado**. Nasce
de uma leitura do dono sobre a proposta errada deste agente: a de separar itens
em uma "comanda irmã" para permitir que cada pessoa pagasse a sua parte. A
correção é a origem desta sprint e vale registrar, porque muda o que se
constrói: **pagador não é comanda**. O hambúrguer foi pedido naquela mesa,
produzido para aquela mesa e entregue naquela mesa; só o seu estado financeiro
mudou. Mover o item para representar quem paga criaria uma associação artificial
que contamina KDS, produção, auditoria, cancelamento, estorno, desconto, taxa de
serviço, fiscal, conciliação e transferência real de mesa.

Objetivo: permitir que uma sessão operacional permaneça aberta e continue
recebendo consumo enquanto partes da obrigação financeira são liquidadas por
diferentes pagadores, preservando rastreabilidade por item, concorrência segura
e independência entre produção e pagamento.

Contexto — **o mecanismo já existe quase inteiro, e o que falta não é pagamento
por item.** A auditoria de 05/09 encontrou construído:

- o ciclo parcial completo. `confirm_intent` põe a negociação em
  `PARTIALLY_COVERED` enquanto sobra saldo e em `COVERED` quando
  `remaining == 0`; `PARTIALLY_COVERED` pertence a `ACTIVE_NEGOTIATIONS`, então
  novas parcelas continuam sendo aceitas; `remaining` é recalculado como
  `total_due − confirmed − receivable_covered`; e `finalize` é comando separado,
  admitido só em `COVERED`. `finalize` já significa "a conta inteira terminou",
  nunca "este pagador terminou";
- a sessão de mesa vai a `PARTIALLY_PAID` na primeira confirmação, e esse estado
  pertence a `ACTIVE_SESSIONS` — a mesa não fecha por ter recebido pagamento;
- **alocação por item**: `PaymentAllocation.order_item_id` existe, e
  `create_intent` valida que o item pertence a um Order da negociação antes de
  persistir;
- **reserva**, mas só no total da conta: `_totals` separa `processing_amount` das
  parcelas `PENDING`/`PROCESSING`, e `create_intent` só aceita
  `remaining − processing`. O intervalo entre criar e confirmar já é respeitado
  no agregado;
- **lock transacional**: `_locked_negotiation` faz `SELECT ... FOR UPDATE` na
  negociação, e `create_intent` e `confirm_intent` passam por ele. Dois terminais
  pagando a mesma conta já serializam.

O que falta é a semântica. A negociação hoje é o **snapshot congelado de uma
conta que está fechando**, e o que a operação real pede é uma **conta viva que
vai sendo liquidada**:

```text
hoje                          contratado
"vou fechar a conta"          mesa aberta, consumo continua
  → snapshot                    → Marcelo paga alguns itens → PARTIALLY_COVERED
  → consumo muda                → entram itens novos → a conta absorve o saldo
  → INVALIDATED                 → Astra paga outros itens
                                → último saldo pago → COVERED → FINALIZED
```

Os quatro pontos concretos que impedem o comportamento contratado:

1. **Consumo novo mata a conta.** `_validate_source` compara a versão da sessão
   com `negotiation.source_version` e, ao ver diferença, marca `INVALIDATED` e
   responde 409 "O consumo mudou. Reabra a conta". Lançar uma cerveja depois de
   Marcelo pagar impede o pagamento seguinte. Os pagamentos não se invalidam
   entre si — `confirm_intent` ressincroniza `source_version` —, mas o consumo de
   fora derruba;
2. **`order_item_id` é escrito e nunca lido.** Não há soma por item, nada compara
   as alocações com o total do item, e a projeção devolve as alocações cruas.
   Hoje dois pagadores podem alocar o mesmo whisky, desde que o total da conta
   feche;
3. **Não existe pagador.** `PaymentIntent` tem `created_by` e `confirmed_by`, que
   são o operador. Quem pagou não é registrado em lugar nenhum;
4. **`cancel_item` não tem guarda financeira nenhuma.** Ele exige apenas que o
   Order esteja `OPEN` e cancela. Sob o modelo de snapshot isso ficava mascarado
   pela invalidação; numa conta viva, é o caminho para cancelar um item que
   alguém já pagou.

Entregas, em cinco contratos:

**1. Live negotiation reconciliation.** A negociação absorve mudança compatível
do consumo em vez de invalidar: `total_due` é recalculado, `NegotiationOrder`
ganha as linhas novas, `source_version` acompanha, e nenhuma parcela confirmada
nem alocação existente é tocada. A fronteira **não** é "aditivo absorve,
alteração recusa" — é econômica e vale por item:

```text
item_total_depois_da_mudança  >=  settled_amount + reserved_amount
```

Assim, cancelar uma pizza de R$ 60 que ninguém pagou é permitido e derruba o
devido; reduzir para R$ 30 um whisky de R$ 40 já liquidado é recusado; e uma
pizza de R$ 80 com R$ 20 liquidados aceita mudanças que a mantenham em R$ 20 ou
mais. A regra é mais forte do que bloquear qualquer item que tenha alocação, e é
o que `cancel_item`, `transfer_item` e a edição de quantidade passam a consultar.

**2. Item settlement projection.** Por `OrderItem`: `item_total`,
`settled_amount`, `reserved_amount`, `available_amount` e `is_paid`, com
`available = item_total − settled − reserved`, resolvidos no servidor. Enquanto
o cartão do Claude está passando, o segundo terminal lê "em pagamento" no
whisky, e não "disponível R$ 40". Confirmação move `reserved → settled`; falha,
cancelamento ou expiração devolve `reserved → available`.

**3. Allocation invariants.** Nenhuma alocação pode liquidar ou reservar acima do
disponível econômico do item. `amount` é a única verdade financeira: **não** se
guarda `quantity` na alocação, porque duas fontes canônicas podem discordar e
"metade da pizza" não tem quantidade inteira. A tela oferece "1 de 4 cervejas ·
R$ 12" derivando de `amount / unit_price`, e o ledger guarda `amount`. Isso
atende rateio, couvert, desconto e item compartilhado sem deformar o modelo.

**4. Payer identity.** A parcela passa a registrar quem pagou, sem confundir com
o operador que executou. `payer_label` textual, obrigatório o bastante para a
tela dizer "PAGO · Marcelo", mais `customer_id` opcional para o dia em que o
valor for lançado na conta de um cliente cadastrado ou de uma empresa. Nenhum
cadastro é exigido para dividir uma conta entre amigos.

**5. Concurrent settlement safety.** Dois terminais nunca se apropriam do mesmo
saldo. O lock que já existe em `_locked_negotiation` é a base, e o cálculo por
item passa a acontecer **dentro** dessa mesma transação — recalcular
`item_total`, `settled` e `reserved`, exigir `requested <= available` e só então
criar a reserva. Fica registrado um buraco que o lock atual não cobre e que esta
sprint fecha: `uq_active_negotiation_scope` impede duas negociações ativas com o
mesmo `scope_key`, mas `table-session:<id>` e `orders:<id>` são chaves
diferentes, de modo que uma conta da mesa e uma conta de uma comanda daquela
mesma mesa podem coexistir e alocar os mesmos itens.

`COVERED` deixa de ser terminal, e isso é contrato, não detalhe. Conta de R$ 100
integralmente paga, e antes de o operador finalizar alguém pede mais duas
cervejas: a negociação volta a `PARTIALLY_COVERED` com `remaining = R$ 24`.
`COVERED` significa apenas "neste instante, todo o consumo conhecido está
coberto". O ponto irreversível é `FINALIZED` — depois dele não entra consumo,
não entra alocação e não há alteração ordinária; correção passa a ser estorno,
cancelamento, refund ou ajuste fiscal, pelos fluxos próprios.

```text
OPEN → PARTIALLY_COVERED ⇄ COVERED → FINALIZED
         ↑ mais consumo, mais pagamentos ↓
```

Só então a interface, e a economia do desenho aparece aqui: **pagar tudo,
dividir por pessoa e pagar por itens deixam de ser três funcionalidades.** São
três formas de construir `PaymentAllocation` sobre o mesmo motor de settlement.

- **Pagar tudo** — toma todo o saldo aberto da comanda;
- **Dividir por pessoa** — quatro pessoas, saldo de R$ 400, R$ 100 para cada,
  com ajuste;
- **Pagar por itens** — marca hambúrguer e coca, total R$ 45, paga; os itens
  passam a aparecer como `PAGO · Marcelo` e saem da lista do próximo pagador. A
  mesa continua aberta.

Gate:

- consumo novo entra numa conta parcialmente paga sem invalidar nada: as
  parcelas confirmadas permanecem, as alocações por item permanecem, e o devido
  cresce;
- cancelar item sem liquidação derruba o devido; cancelar ou reduzir item abaixo
  de `settled + reserved` é recusado, por `cancel_item`, por `transfer_item` e
  por qualquer edição de quantidade;
- **estado de produção não é alterado por operação de pagamento, em nenhum
  caminho.** `PENDING`, `PREPARING`, `READY` e `DELIVERED` respondem à cozinha;
  `OPEN`, `PARTIALLY_PAID` e `PAID` respondem ao caixa. Um whisky `DELIVERED +
  PAID`, uma pizza `DELIVERED + OPEN` e um hambúrguer `PREPARING + OPEN`
  convivem na mesma comanda;
- a guarda `READY`/`DELIVERED` de `transfer_item` **não é enfraquecida**: ela
  protege operação de produção concluída, e nada nesta sprint pede que um item
  mude de comanda para ser pago;
- dois terminais tentando pagar o mesmo whisky: um reserva, o outro lê
  `available = 0` e vê "em pagamento" — provado por teste com transações
  concorrentes reais, não por checagem sequencial em Python;
- parcela que falha, é cancelada ou expira devolve o saldo do item a
  `available`, e o item volta a ser pagável;
- Σ alocações de um item nunca excede o total do item, provado por teste que
  reprova se conseguir;
- `COVERED` volta a `PARTIALLY_COVERED` quando entra consumo antes da
  finalização, com teste explícito;
- depois de `FINALIZED` não entra consumo nem alocação;
- uma conta da mesa e uma conta de uma comanda daquela mesa não podem alocar o
  mesmo item;
- isolamento tenant/store e permissions testados negativamente;
- migration com upgrade, downgrade e drift check verdes.

Dependências e fronteiras: depende do S8 (negociação, parcelas, alocações) e do
S12 (sessão, comandas, linhagem), ambos concluídos no gate interno. **Não**
depende de homologação de provider — a divisão funciona com dinheiro, PIX e
cartão manual, e o TEF só torna a reserva mais visível, porque nele o intervalo
entre criar e confirmar a parcela é real. Fecha a dívida "Conta não pode ser
dividida por pessoa" da seção 9 e substitui a proposta de comanda irmã, que fica
registrada como **recusada** para que ninguém a reintroduza.

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

ATENDIMENTO E CONTA VIVA
S8 + S12 → S25 Liquidação progressiva da comanda
S23 → seletor compartilhado PDV/comanda (metade aberta)

OMNICHANNEL
S4 + S6 → S10 Channel Hub
S4 + S8 + S10 → S13 Channel Catalog/Reconciliation

CRÉDITO E FINANCEIRO
S8 → S14 Receivables → S15 Cobrança/Renegociação
S8 + S9 + S13 + S14 + S15 → S16 Cash/Fiscal/Reconciliation

GESTÃO E PLATAFORMA
S11 + S12 + S13 + S14 + S15 + S16 → S17 BI
S2 + fontes de saúde de S8–S17 → S18 Dashem Control Completion
S18 + contratos SaaS → S18.1 Owner Financeiro SaaS e minimização operacional
capabilities reais de S9–S18 → S19 Capability Profiles

PILOTO
S8–S19 → S20 Hardening/Pilot Readiness → S21.1 Acesso e dispositivos → S21 Piloto Comercial
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
| Crediário tratado como pagamento recebido | S14 | recebível e allocation distintos | resolvido no S14 |
| Renegociação capaz de alterar documento original | S15 | acordo e ledger imutáveis | resolvido no S15 |
| Caixa/fiscal/provider sem conciliação unificada | S16 | fatos vinculados sem reescrita | resolvido no S16 |
| BI agregado ou inventado no browser | S17 | read models rastreáveis | resolvido e testado no S17 |
| Login gerencial misturado com acesso operacional | OA-1–OA-4 | superfícies independentes, código + PIN pessoal e terminal autorizado | resolvido e testado na matriz OA-4 `14/14` |
| Gestão define ou redefine o PIN definitivo | OA-2 | ativação temporária; colaborador define o próprio PIN | resolvido e testado na matriz OA-4 |
| POS pede tenant/unidade/caixa depois do PIN | OA-1 | contexto derivado somente do terminal + sessão | resolvido e testado na matriz OA-4 |
| CI valida componentes, mas não a jornada real | OA-4 | Playwright + evidência no deploy | resolvido pelo CI e pela repetição credenciada `14/14` no deploy |
| Impressora sem tela tratada como usuário ou referência suficiente | S21.1 | Print Bridge pareado e revogável | contrato definido; implementação/hardware pendentes |
| Endpoint de identidade e saúde ainda amplos | S18 | routers e observabilidade por domínio | resolvido: router Control e instrumentação explícita |
| Control expõe caixas, vendas, unidades em operação ou quadro de funcionários do tenant | S18.1 | somente contrato, cobrança SaaS e observabilidade técnica no Owner | **resolvido e protegido por testes no primeiro sprint** |
| Cobrança SaaS limitada a campos editáveis da assinatura | S18.1 | faturas, recebimentos, inadimplência e métricas SaaS rastreáveis | **planejado** |
| Imagem do produto listada no S4 e nunca entregue na interface | S4 → 5.4.4 → **S24** | cadastro, listagem e PDV exibindo mídia persistida | **resolvido no S24, entregue em 05/09/2026**: `primary_media_asset_id`, resolvedor determinístico, projeção resolvendo N imagens em uma chamada, biblioteca DASHEM e upload privado integrado ao cadastro. `image_url` permanece como compatibilidade, nunca reescrita. Verificado na tela pelo dono em 05/09 |
| Ordenar o próprio botão exige poder sobre o catálogo inteiro | S23 | permission de layout separada da permission de catálogo | **resolvido no S23, entregue em 05/09/2026**: `catalog.layout.manage` e `catalog.layout.personalize` criadas na migração `073`, semeadas nos perfis e exigidas pelas rotas de layout. Um caixa ordena os próprios atalhos sem receber poder sobre produtos e preços |
| Acesso rápido grava uma posição por vez e recusa posição ocupada | S23 | reorder atômico do array inteiro, com versão e auditoria | **resolvido no S23, entregue em 05/09/2026**: o `PUT` recebe a lista inteira com versão esperada, e as uniques de posição das duas tabelas passaram a `DEFERRABLE INITIALLY DEFERRED`. Colisão real responde **409**, nunca 500 |
| Comanda lança item por identificador, sem a vitrine que o balcão já tem | S23 (metade aberta) | um seletor visual compartilhado, com comando distinto por jornada | **dívida aberta, apurada em 05/09**: `ProductShowcase` é consumido só por `QuickProductGrid`. `TableServiceWorkspace` chama `addOrderItem` a partir de um campo de identificador de produto — sem foto, sem categoria e sem busca. O contrato do S23 previa o componente compartilhado; entregou-se o balcão |
| Atividade contratada sem efeito sobre o conteúdo publicado | 5.4.0 + 5.4.1 | atividade como dimensão do sortimento, resolvida no servidor | resolvido em 03/09: `assortments.business_activity`, migration 070, recusa 403 para atividade não contratada |
| Conjunto legado publicando conteúdo de outro nicho no PDV | 5.4.0 | decisão administrativa explícita para reclassificar ou aposentar | resolvido em 03/09: ação de Gestão publica o conjunto da atividade e aposenta o não classificado, sem apagar nada |
| Vocabulário do console assumindo alimentação para todo tenant | 5.4.4 | termo por atividade como dado extensível | **corrigido por condicional binário em 03/09; classe do problema em aberto** |
| Conteúdo inicial por atividade em constante compilada | 5.4.4 | dado versionado e auditável, restrito a tenant interno ou de teste | **dívida aberta, criada em 03/09** |
| Atividade ativa do PDV mantida apenas no cliente | 5.4.4 + Gate B | escolha persistida na sessão operacional e auditável | **dívida aberta, criada em 03/09** |
| Junção de mesas existe no servidor e não na tela | S12 | mesclagem alcançável pelo garçom, com linhagem visível | resolvido e testado em 04/09: item, comanda, sessão, separação para mesa livre, mesclagem e histórico estão alcançáveis na operação |
| Conta não pode ser dividida por pessoa | **S25** | alocação por item sobre uma conta viva, sem mover item de comanda | **reaberta e reclassificada em 05/09**: o que foi resolvido em 04/09 é pagar *uma comanda inteira* em parcelas mantendo as demais ativas. Dividir por item dentro de uma comanda — Marcelo paga o hambúrguer, Astra paga o whisky, o resto segue aberto — não existe. A proposta deste agente de separar itens em uma comanda irmã foi **recusada pelo dono em 05/09**: pagador não é comanda, e mover o item contamina KDS, produção, auditoria, estorno, fiscal e conciliação |
| Negociação invalida ao ver consumo novo | S25 | conta viva que absorve o saldo acrescentado | **dívida apurada em 05/09**: `_validate_source` compara a versão da sessão com `source_version` e marca `INVALIDATED` na primeira diferença. Depois de alguém pagar, uma cerveja lançada na mesa impede o pagamento seguinte. A negociação é snapshot de fechamento, e a operação real pede liquidação progressiva |
| `order_item_id` é escrito na alocação e nunca lido | S25 | projeção de settlement por item com invariante de saldo | **dívida apurada em 05/09**: nada soma alocações por item nem compara com o total dele. Dois pagadores podem alocar o mesmo whisky desde que o total da conta feche. Falta `settled`/`reserved`/`available`/`is_paid` por item |
| Parcela registra o operador e não o pagador | S25 | `payer_label` e `customer_id` opcional na parcela | **dívida apurada em 05/09**: `PaymentIntent` tem `created_by` e `confirmed_by`, que são quem operou. Não há como a tela dizer "PAGO · Marcelo", nem lançar o valor na conta de um cliente cadastrado |
| `cancel_item` não consulta cobertura financeira | S25 | `item_total >= settled + reserved` como fronteira única | **dívida apurada em 05/09**: `cancel_item` exige apenas que o Order esteja `OPEN`. Sob o snapshot isso ficava mascarado pela invalidação; numa conta viva é o caminho para cancelar um item já pago |
| Conta da mesa e conta de uma comanda dela podem coexistir | S25 | mesmo item nunca alocado por duas negociações | **dívida apurada em 05/09**: `uq_active_negotiation_scope` impede duas negociações ativas no mesmo `scope_key`, mas `table-session:<id>` e `orders:<id>` são chaves diferentes |
| SmartPOS existe só como meio de pagamento, não como superfície de operação | S22 proposto em 04/09 | execução local distinta de `TEF_BRIDGE`, com adapter homologado e sem login humano na maquininha | **lacuna levantada em 04/09**: `PaymentDeviceExecutionModeEnum.SMARTPOS` trata a maquininha como destino de cobrança. Um SmartPOS de campo roda o ponto de venda inteiro, e isso não está modelado em lugar nenhum |
| Owner tratado como domínio e não como camada | [ADR-029](../architecture/adr-029-module-boundaries-and-owner-layer.md) | nenhum serviço de tenant lê tabela do Owner; direitos consultados por contrato | **regra dura estabelecida em 04/09**, sem baseline e sem exceção prevista. Verificada por `test_no_tenant_module_reaches_into_the_owner_layer`, hoje verde |
| Cadastro de dispositivo não distingue ponto de operação, navegador e periférico | S21.1 | pareamento verificado por tipo, com credencial de dispositivo em vez de texto livre | **dívida aberta, criada em 04/09**: `operational_devices` guarda POS, KDS e PRINTER na mesma forma, e o periférico é declarado por uma string `configuration_ref` que ninguém valida. Na tela, cadastrar impressora ou terminal de produção pede um texto do tipo `bridge://cozinha/impressora-01` sem provar que o bridge existe. Maquininha não passa por aqui: vive em `PaymentDeviceBinding` (S9), em outro módulo, sem que a tela de terminais diga isso |
| Autoatendimento tem contrato de capability e nenhuma superfície | **S22 proposto em 04/09, não autorizado** | superfície própria, com identidade de dispositivo, sem sessão humana e com autoria de serviço | **corrigido em 04/09**: a afirmação anterior deste agente, de que autoatendimento não existia em lugar nenhum, era **falsa**. `self_checkout` está no `CAPABILITY_REGISTRY` — escopo TERMINAL, requer `barcode_scanning` e `payments` — e está deliberadamente fora de `IMPLEMENTED_CAPABILITIES`, junto de outras oito. O contrato existe; a superfície não. O S22 deve partir dele, não inventar chave nova |
| Reativar um terminal não devolve a autorização do navegador | S21.1 + Gate B | pausa reversível que preserve o pareamento, distinta da revogação | **decisão pendente, levantada em 04/09**: qualquer troca de status zera `authorization_version`, `authorized_at` e `authorization_expires_at` em `device_service`. Pausar equivale, na prática, a desparear, e exige alguém no balcão entrando por e-mail para reautorizar |
| Mesa e comanda operam sem turno de caixa | a decidir | política explícita entre salão livre e turno obrigatório | **decisão pendente, levantada em 04/09**: `table_service` não referencia caixa em ponto algum, então consumo é lançado com o caixa fechado e fica sem turno a que pertencer. Recomendação registrada: manter o lançamento livre e exigir turno aberto para **pagar**, nunca para consumir |
| `CapabilityConflict` é modelo sem uso | Capability Mesh | detecção e resolução de conflito entre capabilities contratadas | **dívida apurada em 04/09**: a tabela existe em `platform.py` e é reexportada, e **nenhum código a lê ou escreve**. O mesh declara dependências e as resolve topologicamente com detecção de ciclo, mas conflito é só estrutura vazia |
| Coerência entre capability e atividade é condicional fixa | Capability Mesh + 5.4.4 | regra por atividade como dado, junto do contrato da capability | **dívida apurada em 04/09**: `capability_allowed_by_activity` trata **apenas** `table_service`, por `if` explícito. É o mesmo defeito de classe do vocabulário por nicho — funciona para o caso conhecido e não tem onde declarar o próximo |
| Modularização iniciada e abandonada | transversal, [ADR-029](../architecture/adr-029-module-boundaries-and-owner-layer.md) | fronteira de módulo por domínio, Owner como camada, dono declarado por tabela | **sob contenção desde 04/09**: o mapa, a direção da dependência e a regra do Owner estão declarados e **defendidos por teste** (`test_module_boundaries.py`). A medição encontrou apenas **8 travessias**, das quais 5 são `Register` e `SalesChannel` morando no arquivo errado. Enquanto o baseline tiver linhas, o sistema não está modularizado — está contido, com a dívida contada |
| Segurança/confiabilidade deixadas para o fim | contínuo + S20 | gate por sprint e prova combinada | política corrigida |
| Cliente capaz de escolher o autor de uma mutação | Gate A | ator derivado do principal ou service actor emitido pelo servidor | resolvido e testado; retirada dos campos legados fica para evolução de contrato |

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

## 11. Gates corretivos após S21.1

### Gate A — autoria server-side

Conclui o ADR-020: auditoria, idempotência e eventos usam a identidade
autenticada ou um service actor persistido pelo servidor. Identificadores
declarados pelo cliente não concedem autoria e divergências são recusadas antes
da mutação.

### Gate B — autoridade operacional persistida

Implementa o ADR-021. A autorização do terminal e o acesso operacional deixam de depender
somente de JWT e passam a possuir versões e registros server-side revogáveis.
Pausa, reativação, reautorização, redefinição de credencial, alteração funcional e fim
de turno invalidam a autoridade anterior. Pessoa, turno, POS, TEF Bridge e Print
Bridge continuam identidades independentes. Os dez critérios de aceite do
ADR-021 permanecem obrigatórios, acrescidos do contrato de acesso do colaborador
e da prova ponta a ponta do ADR-024.

Estado: **PASSED em 4 de setembro de 2026**, por decisão do dono do SaaS. O
núcleo persistido, heartbeat, expiração e revogação estão implementados.
OA-1–OA-3 corrigiram a separação das superfícies, o PIN sob controle do
colaborador e o contexto exclusivo da sessão operacional. As duas condições que
faltavam foram cumpridas: o job `Operational access E2E` está verde no CI, e a
matriz OA-4 fechou `14/14` na repetição assistida contra o deploy publicado
([dossiê](../quality/oa4-credentialed-acceptance-2026-09-03.md)).

Ressalva que acompanha a promoção: o **cenário 14 foi reescrito durante a
execução**, também por decisão do dono do SaaS, porque o critério original
contradizia a matriz de permissões da migração 017 e inviabilizava o
comerciante que trabalha sozinho. O gate foi avaliado pelo critério revisado —
turno responde a pessoa nomeada, ninguém opera sob identidade alheia, permissão
exigida por rota — e não pelo original. A revisão está no ADR-024.

O que **não** foi promovido junto: a identidade de periférico do S21.1
permanece aberta, e o Print Bridge e a homologação de TEF seguem independentes.

### Gate C — execução de pagamentos vinculada ao dispositivo

Conclui o ADR-022. A execução de cartão recebe somente um
`PaymentDeviceBinding` persistido; o servidor recompõe e valida a cadeia
tenant → unidade → caixa → POS → provider → meio de execução. Um bridge TEF
precisa corresponder ao mesmo caixa e provider, e uma sessão operacional não
pode executar no POS ou caixa de outro vínculo. SmartPOS pode ser cadastrado
como pareamento, mas permanece não executável até existir adapter homologado —
nunca simulado como uma cobrança real. Pausa e revogação do vínculo impedem
novas execuções, sem alterar transações já registradas.

Estado: **PASSED em 4 de setembro de 2026.** A implementação já existia inteira
em `provider_service._resolve_execution_binding`, que reconstrói a cadeia na
mesma transação: tenant e unidade, caixa e POS ativos do vínculo, configuração
de provider ativa da mesma unidade, modo de execução e, para TEF, o bridge
pareado àquele caixa e provider. O que faltava era a prova, e a auditoria estava
parcialmente errada sobre ela: o teste do S9 já cobria três dos oito critérios do
ADR-022 — payload legado recusado, bridge offline sem bloquear outros meios, e
SmartPOS recusado explicitamente.

A matriz de cruzamento que faltava está em `tests/test_gate_c_payment_device_binding.py`:
vínculo do tenant vizinho recusado nos dois sentidos com intent próprio de cada
lado; vínculo pausado que deixa de executar e volta a executar ao ser reativado;
POS revogado que órfã o vínculo ainda existente; e — no nível de serviço, porque
a suíte HTTP roda sob `AUTH_MODE=disabled` e nunca entra no ramo — um turno PIN
que só executa pelo seu próprio POS, com dois terminais no mesmo caixa
compartilhando o bridge que pertence ao caixa.

O gate externo de homologação de cada provider e do SmartPOS permanece
independente e continua aberto.

### Gate D — auditoria imutável e projeções de produtividade

Conclui o ADR-023. Solicitação, autorização, execução e resultado de pagamento
passam a ser fatos append-only com tenant, unidade, caixa, POS, sessão,
operador, ator de serviço, vínculo e transação preservados. O PostgreSQL impede
`UPDATE` e `DELETE` das trilhas de auditoria, inclusive fora do ORM. A
produtividade operacional é uma projeção persistida por sessão operacional do
colaborador, com fórmulas
publicadas, watermark e reconstrução integral a partir dos fatos. Testes
negativos atravessam tenant, unidade, dispositivo e sessão.

Estado: **PASSED em 4 de setembro de 2026**, depois da leitura própria que o
Gate C não substituiu.

O que já estava provado por `test_gate_d_payment_audit.py`: os quatro estágios
como fatos distintos e ordenados, os três gatilhos de imutabilidade recusando
`UPDATE` e `DELETE` fora do ORM, uma unidade irmã sem enxergar evento algum, e a
produtividade persistida, reconstruível e publicada com fórmulas.

O que faltava, agora em `tests/test_gate_d_audit_completeness.py`:

- **critério 2** é uma verificação de seis partes e o teste antigo variava
  quatro. Vínculo do caixa vizinho e caixa divergente do vínculo passam a ser
  recusados com 403 antes do primeiro evento, e nada é escrito por nenhuma das
  duas recusas — são justamente os dois elementos que um chamador erra sem
  má-fé;
- **critério 3**: o bridge reporta o resultado sob o próprio principal, e o
  evento preserva operador, turno e dispositivo de origem. Autoria humana e
  autoria de serviço ficam lado a lado, nunca fundidas;
- **critério 4**: `UNKNOWN` repetido não vira dois fatos, `UNKNOWN → CONFIRMED`
  acrescenta um fato novo em vez de reescrever o antigo, `CONFIRMED` repetido não
  duplica, e `EXECUTED` é escrito uma única vez por mais resultados que cheguem.

Fórmulas publicadas em `PRODUCTIVITY_FORMULAS`, com watermark e versão no
endpoint, consumidas por `DashboardBI` — a interface não reduz transação no
navegador.

## 12. Próximo passo autorizado por este roadmap

**Autorizado e executado em 05/09/2026: o S13.** Com S23 e S24 fechados no gate
interno, o trabalho autorizado foi dar maçaneta à janela do Channel Catalog, e
ele está feito: cinco das seis rotas de escrita — mapeamento por merchant,
oferta, lote de publicação, repasse e pagamento de repasse — chegaram ao cliente
e à tela. A sexta, o resultado item a item, ficou fora por decisão de desenho:
é a resposta do adapter, e um botão para ela deixaria uma pessoa assinar a
palavra do marketplace. A certificação de canal permanece um gate externo e
independente: nada disso antecipa piloto comercial.

**Contratado em 05/09/2026, ainda não iniciado: o S25 — Liquidação progressiva
da comanda.** A conversa que o produziu começou como "dividir a conta" e terminou
mudando o que a negociação é: de snapshot congelado de um fechamento para uma
conta viva que recebe consumo enquanto vai sendo liquidada por vários pagadores.
A auditoria de 05/09 mostrou que o ciclo parcial e a alocação por item já estão
construídos; o que falta é a semântica, a projeção por item, o pagador e a
segurança sob concorrência entre terminais. Fica registrado o que foi **recusado**
no caminho: separar itens em uma comanda irmã para representar quem paga.

Continuam em aberto, sem contrato: o fechamento de balcão do S8, ainda no caminho
antigo de `Sale`; a metade "comanda" do S23; e os periféricos do S21.1.

O Gate B foi **fechado em 04/09/2026** e não bloqueia mais o pré-piloto. O ciclo
que o fechou foi:

```text
OA-1 autoridade/contexto
  → OA-2 ativação e PIN pessoal
    → OA-3 superfície operacional acessível
      → OA-4 E2E + evidência no deploy
        → nova decisão do Gate B
```

O plano executável está em
[`operational-access-hardening-plan.md`](operational-access-hardening-plan.md).
Funcionalidades novas e homologações de campo não antecedem essa decisão.

Execução em 03/09/2026: a primeira rodada assistida contra o deploy publicado
aprovou os cinco cenários alcançáveis sem credencial — login exclusivamente
gerencial, navegador sem autorização sem formulário de código e PIN, entrada
operacional sem rolagem horizontal de 360 a 1366 px, foco visível com 21,00:1 e
título com 20,17:1. A evidência está em
[`oa4-deploy-acceptance-2026-09-03.md`](../quality/oa4-deploy-acceptance-2026-09-03.md).

Os catorze cenários que exigem terminal autorizado, código ativado e PIN pessoal
foram executados em produção em 04/09/2026, **14/14**, na rodada credenciada
registrada em
[`oa4-credentialed-acceptance-2026-09-03.md`](../quality/oa4-credentialed-acceptance-2026-09-03.md).
Com isso o OA-4 está concluído e o Gate B foi promovido a `PASSED` em 04/09/2026,
por decisão do dono do SaaS. Duas capturas de estado ficaram declaradas como
lacuna na própria evidência: a de ativação inicial exibe código temporário e
exige tarja, e o estado offline foi coberto pela suíte de aceitação em vez de
captura manual.

Trabalho executado fora desta sequência entre 02 e 03/09/2026 — atividade como
dimensão do sortimento, publicação do conjunto por atividade, seletor de negócio
no PDV, vocabulário por nicho, imagem de produto, responsividade e correção de
contraste — está registrado nos Gates 5.4.0, 5.4.1, 5.4.3 e 5.4.4 da trilha
corretiva e nas linhas de dívida da seção 9. Nada disso promove gate por si só.

S23, S24 e o S13 foram fechados no gate interno em 05/09/2026, com a metade
"comanda" do seletor compartilhado registrada como dívida na seção 9.
S0–S17, S18–S20 e o Gate A preservam suas implementações internas. S17.1–S17.3 e
o Gate B foram **fechados em 04/09/2026** pela jornada real, com os catorze
cenários credenciados executados no deploy; S21.1 continua aberto pela metade dos
periféricos — protocolo do Print Bridge e pareamento verificado de dispositivo —
e S21 permanece `NO-GO`, por homologação de provider e certificação de canal, que
são contrato, credencial e hardware de terceiros. O S13 introduziu o ADR-009,
mapeamentos por merchant, ofertas versionadas, publicação item a item e documentos
de repasse independentes do Order. Falha parcial e diferença financeira ficam
observáveis. O S13.1 completa a primeira retaguarda operacional do tenant e fixa
a fronteira Gestão → PDV/KDS, nunca no sentido inverso. O S14 fecha o primeiro
contrato de crediário sem tratar obrigação como recebimento. O S15 adiciona
baixas e acordos imutáveis. O S16 fecha caixa, fiscal, estornos e conciliação
com fatos compensatórios e sem reescrita. O S17 cria projeções incrementais e
reconstruíveis, com fórmulas, lag e drill-down rastreáveis. O S17.1 fixa a
fronteira e-mail/acesso operacional, o papel Supervisor e a chegada de reservas
sem apagar histórico. O ADR-024 corrige a ida ao PDV: a sessão gerencial
autoriza a infraestrutura, mas cada operação humana exige colaborador, função,
código + PIN pessoal e sessão. O S18 conclui os contratos próprios do Control sem invadir a
equipe cotidiana do tenant. S19–S21 consolidam profiles, hardening e prontidão
interna. C e D preservam migrations, testes negativos e CI verde; o Gate B já
possui a prova operacional exigida. Homologações TEF, SmartPOS e
Print Bridge continuam gates próprios posteriores e não são simuladas pelo
produto.
