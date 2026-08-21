# Arquitetura da Plataforma Dashem Commerce

Status: decisão arquitetural aprovada para evolução incremental do Dashem POS.

## 1. Visão do produto

O Dashem POS é uma superfície operacional de uma plataforma de comércio. A
plataforma deve atender desde uma operação de bairro até redes com múltiplas
unidades, terminais e canais, sem criar forks de código por cliente ou segmento.

```text
Plataforma Dashem
└── Tenant (cliente/organização)
    └── Site (loja, filial, depósito, cozinha ou unidade)
        ├── Terminais e dispositivos
        ├── Canais de venda
        ├── Catálogo, preços e estoque
        └── Pedidos, vendas, pagamentos e fulfillment
```

As três dimensões são independentes:

- multi-tenant: vários clientes com isolamento estrito;
- multi-site: várias unidades por cliente;
- multi-terminal: vários pontos operacionais por unidade.

## 2. Princípios inegociáveis

1. Nenhum tenant, operador, catálogo, preço ou segmento é hardcoded.
2. Toda operação comercial persistida possui `tenant_id`; operações locais
   também possuem `site_id`.
3. Identidade vem de autenticação verificada. Headers fornecidos pelo cliente
   não são prova de identidade e serão removidos como mecanismo de confiança.
4. Autorização é aplicada no serviço e no banco, com menor privilégio.
5. Toda mutação relevante produz auditoria e evento de domínio na mesma
   transação.
6. Integrações e retries são idempotentes.
7. IA não fica no caminho crítico de venda, pagamento ou estoque.
8. Nenhum agente acessa tabelas diretamente; agentes usam ferramentas de
   domínio autorizadas, validadas e auditadas.
9. Interfaces são orientadas por tarefa, papel, dispositivo, volume e
   capacidades habilitadas, não por forks visuais por cliente.
10. Dados reais, estados vazios reais e métricas reais substituem demonstrações
    cosméticas.

## 3. Planos da plataforma

### 3.1 Control Plane

Uso exclusivo da equipe Dashem:

- leads e qualificação;
- provisionamento e ciclo de vida de tenants;
- planos, limites e capabilities;
- onboarding;
- suporte assistido com prazo, motivo e auditoria;
- saúde, erros e integrações;
- auditoria global.

Papéis iniciais: `PLATFORM_OWNER`, `PLATFORM_ADMIN`, `SALES`, `SUPPORT`,
`OPERATIONS` e `AUDITOR`.

O fluxo de responsabilidade é explícito:

```text
Dashem Control
└── provisiona a organização e as estruturas contratadas
    └── entrega o acesso ao administrador contratual
        └── o cliente organiza sua própria empresa
            ├── administradores
            ├── gerentes e supervisores
            ├── caixas e operadores
            └── auditores
```

O Control Plane não atribui funções internas do cliente. Ele controla contrato,
plano, limites, capabilities contratadas e ciclo de vida da organização. A
administração do tenant controla usuários, papéis, permissões e escopos por
unidade dentro desses limites.

### 3.2 Commerce Plane

Uso dos clientes:

- identidade, memberships e escopo por site;
- organizações, sites, terminais e dispositivos;
- catálogo, variantes, modificadores, combos, serviços e unidades de medida;
- preços por site e canal;
- estoque e movimentações;
- pedidos omnichannel, PDV, pagamentos e fiscal;
- produção, retirada, entrega e demais formas de fulfillment;
- relatórios e auditoria do tenant.

### 3.3 Intelligence Plane

Base para Harness, agentes e graph context:

- eventos de domínio versionados;
- outbox transacional;
- context graph com origem e rastreabilidade;
- registro de ferramentas de domínio;
- execuções de agentes e chamadas de ferramentas;
- aprovações humanas;
- traces, custo, latência, avaliação e erros.

O context graph começa sobre PostgreSQL e relações explícitas. Um banco de
grafos somente será adotado quando consultas e escala demonstrarem necessidade.

## 4. Limites modulares

O backend inicia como monólito modular:

```text
platform     leads, tenancy, planos, capabilities, suporte
identity     usuários, autenticação, memberships e RBAC
sites        unidades, terminais e dispositivos
catalog      itens vendáveis, categorias, variantes e modificadores
pricing      preços, promoções e regras comerciais
inventory    saldos, ledger, receitas e reposição
orders       pedidos, canais, fulfillment e estados
sales        checkout e snapshots comerciais
payments     recebimentos, estornos e conciliação
fiscal       documentos e eventos fiscais
reliability  outbox, idempotência, auditoria e correlation IDs
intelligence contexto, ferramentas, agentes, aprovações e evals
```

Esses limites são contratos de extração futura, não uma obrigação de criar
microserviços prematuramente.

## 5. Identidade e autorização

`User` representa uma identidade global. O vínculo organizacional vive em
`Membership`:

```text
User ──< Membership >── Tenant
                  └──── Site opcional
```

- membership sem site possui escopo no tenant conforme o papel;
- membership com site restringe o acesso àquela unidade;
- um usuário pode participar de vários tenants;
- acesso de plataforma é separado em `PlatformMembership`;
- suporte assistido nunca reutiliza silenciosamente a identidade do cliente.

A evolução de segurança prevê tokens curtos, refresh seguro, MFA para o Control
Plane, revogação, sessões, RLS no PostgreSQL e testes negativos de isolamento.

## 6. Capabilities e verticais

Diferenças de segmento são capabilities e módulos, não forks:

- varejo: barcode, variantes, estoque e promoções;
- mercado: peso, alta densidade, balança e grande catálogo;
- food service: modificadores, combos, receita, cozinha e delivery;
- serviços: agenda, profissionais e itens sem estoque;
- rede: catálogo central, preços locais e permissões regionais.

`TenantCapability` controla habilitação e configuração. Entitlements comerciais
e feature flags técnicas são conceitos separados, ainda que possam convergir na
decisão de acesso.

## 7. Pedidos omnichannel

Todo pedido entra no mesmo núcleo com origem explícita:

`POS`, `WHATSAPP`, `MARKETPLACE`, `ECOMMERCE`, `API`, `IMPORT`, `ASSISTED` ou
`OTHER`.

Campos fundamentais:

- tenant, site e canal;
- identificador externo e chave de idempotência;
- forma de fulfillment;
- snapshots de nome, preço, imposto e modificadores;
- timestamps de ocorrência e recebimento;
- estado de sincronização e reconciliação.

Conectores externos são adaptadores. Mudanças em APIs de terceiros não alteram
o núcleo de pedidos.

## 8. Escala e operação offline

- paginação e filtros server-side desde o primeiro endpoint de listagem;
- índices compostos iniciando por `tenant_id` e, quando aplicável, `site_id`;
- importação/exportação por jobs assíncronos;
- projeções de leitura para dashboards e filas;
- idempotência em integrações, terminais e agentes;
- IDs gerados no cliente, `occurred_at` e `sync_status` para futura operação
  offline;
- Device Bridge futuro para impressoras, balanças, gavetas e demais periféricos.

## 9. IA e Harness

Ferramentas devem representar intenções de negócio, por exemplo:

- `consultar_estoque`;
- `criar_pedido_rascunho`;
- `explicar_divergencia`;
- `sugerir_reposicao`;
- `iniciar_suporte_assistido`.

Cada execução registra tenant, ator, escopo, modelo, versão, contexto utilizado,
ferramentas, aprovações, custo, latência, saída e erros. Ações de alto impacto
exigem aprovação humana. Dados de tenants distintos nunca compartilham contexto.

## 10. Sequência de implementação

### Fundação imediata

1. lifecycle de tenants e sites;
2. memberships globais ou restritas por site;
3. papéis de plataforma separados;
4. leads e conversão em tenant;
5. capabilities por tenant;
6. canais de venda normalizados;
7. origem, fulfillment, sincronização e idempotência em vendas;
8. eventos versionados, auditoria opcionalmente platform-scoped e context edges;
9. registros de agent run, tool call e aprovação;
10. testes de integridade e isolamento.

### Próxima fundação

1. autenticação real e sessões;
2. RBAC e policies;
3. RLS;
4. APIs protegidas do Control Plane;
5. onboarding e configuração do tenant;
6. catálogo editável e importável;
7. registry de ferramentas de domínio;
8. observabilidade e evals.

### Marco operacional antes do primeiro tenant piloto

1. configurar Resend em `auth.dashem.tech`, com SPF, DKIM e DMARC;
2. validar convite, recuperação, expiração e MFA do Platform Owner;
3. concluir o Console Owner para leads, tenants, sites e capabilities;
4. persistir e correlacionar eventos de identidade e entrega de e-mail;
5. expor timeline operacional sem tokens ou URLs sensíveis;
6. implementar suporte assistido temporário e auditado;
7. executar testes negativos de RBAC e isolamento entre tenants;
8. criar tenants e sites de teste antes de retomar expansão visual do PDV.

## 11. Critérios de aceite arquiteturais

- uma loja nunca lê ou altera dados de outro tenant;
- um usuário tenant não acessa o Control Plane;
- suporte exige sessão explícita e auditada;
- um retry não duplica pedido, pagamento, estoque ou ferramenta;
- uma falha de IA não impede a operação do caixa;
- um catálogo grande não é carregado integralmente no navegador;
- cada métrica pode ser rastreada até dados persistidos;
- novas verticais são adicionadas por módulos e capabilities.
