# Dashem POS

Plataforma de comércio da Dashem para ponto de venda, gestão, operação
multi-tenant e múltiplas unidades.

> **Estado do projeto:** fundação técnica em desenvolvimento. O frontend e a
> API estão publicados para validação, mas o produto ainda não está pronto para
> uso comercial ou operação em produção por clientes.

## Visão

O Dashem POS não será um PDV preso a um catálogo ou segmento. A plataforma deve
atender desde uma lanchonete ou papelaria até mercados e redes com várias lojas,
terminais e canais, usando módulos e capabilities em vez de forks por cliente.

```text
Plataforma Dashem
└── Tenant (cliente)
    └── Site (loja, filial, depósito, cozinha ou unidade)
        ├── Terminais e dispositivos
        ├── Usuários e permissões
        ├── Catálogo, preços e estoque
        └── Pedidos, vendas, pagamentos e fulfillment
```

## Estado atual

### Entregue como fundação

- monorepo com frontend React/TypeScript/Vite e API FastAPI;
- PostgreSQL local por Docker e banco gerenciado no Supabase;
- frontend publicado na Vercel e backend publicado no Render;
- migrations executadas automaticamente no deploy do backend;
- autenticação baseada no Supabase Auth e autorização de negócio no FastAPI;
- identidade externa desacoplada do usuário interno por `auth_identities`;
- papéis de plataforma separados das memberships dos tenants;
- primeiro usuário `PLATFORM_OWNER` provisionado de forma controlada;
- rotas `/login` e `/owner` no mesmo domínio, com destino resolvido pelo papel;
- telas de primeiro acesso, senha forte e preparação para TOTP MFA;
- endpoints protegidos do Console Owner e testes automatizados da fundação;
- isolamento obrigatório no PostgreSQL com RLS forçado para tenants e sites;
- papel de runtime sem `BYPASSRLS`, separado da autoridade de migrations;
- Alembic como autoridade exclusiva do schema, sem `create_all` no runtime;
- CI independente para frontend, backend com PostgreSQL e ciclo do Alembic;
- primeiro Capability Mesh executável, com contratos versionados, dependências,
  entitlements por tenant e overrides por unidade;
- navegação móvel no Dashem Control e no Admin do tenant;
- tenants clicáveis no Console Owner, com detalhe de unidades e acessos;
- fluxo backend de convite por e-mail, papel e unidade, com membership
  `INVITED` ativada somente após a criação da senha;
- auditoria e outbox para o provisionamento de cada acesso;
- domínio comercial existente do PDV preservado durante a evolução arquitetural.

### Ainda não pronto para produção

- o SMTP padrão do Supabase foi rejeitado para qualquer fluxo real da Dashem;
- o Resend ainda precisa ser configurado e validado com domínio próprio;
- o backend de produção ainda precisa receber `SUPABASE_SECRET_KEY` e
  `APP_URL`; o segredo administrativo nunca pertence ao frontend;
- o primeiro acesso do Owner precisa ser retestado de ponta a ponta após o Resend;
- Google e Microsoft devem ficar ocultos até seus provedores OAuth estarem
  configurados e testados;
- o Console Owner ainda precisa alcançar o nível operacional definido abaixo;
- o isolamento de tenants e unidades já possui os primeiros testes negativos,
  mas cada novo módulo ainda deve ampliar essa matriz antes do primeiro piloto;
- custom domains, observabilidade e runbooks de suporte ainda serão concluídos.

### Ambientes de validação

- aplicação: <https://dashem-pos.vercel.app>
- API: <https://dashem-pos-api.onrender.com>
- health check: <https://dashem-pos-api.onrender.com/health>

Esses endereços são ambientes técnicos de validação, não uma oferta comercial
nem um SLA de produção. Os domínios `app.dashem.tech` e `api.dashem.tech` fazem
parte da topologia alvo.

## Decisões arquiteturais

### Identidade, entrega e controle

Três fronteiras independentes evitam confundir autenticação com envio de e-mail:

```text
Identity Plane   Supabase Auth
                 credenciais, sessões, JWT, recuperação, OAuth e MFA

Delivery Plane   Resend
                 e-mail transacional, reputação, entrega, rejeições e webhooks

Control Plane    Console Owner Dashem
                 tenants, convites, suporte, auditoria e saúde operacional
```

O Supabase Auth é o Identity Provider da plataforma. O SMTP padrão do Supabase
é somente uma facilidade de demonstração e **não faz parte da infraestrutura de
produção da Dashem**.

O transporte transacional adotado é o **Resend**, usando domínio e reputação
controlados pela Dashem. A topologia alvo é:

```text
dashem.tech
├── app.dashem.tech
├── api.dashem.tech
├── auth.dashem.tech
│   └── acesso@auth.dashem.tech
└── status.dashem.tech        # futuro
```

`auth.dashem.tech` terá SPF, DKIM e DMARC. Segredos SMTP nunca serão enviados ao
frontend, armazenados no Git ou expostos em variáveis `VITE_*`.

Detalhes: [`docs/architecture/identity-email-delivery.md`](docs/architecture/identity-email-delivery.md).

### Plataforma de comércio

A arquitetura multi-tenant, multi-site, omnichannel e agent-ready está em
[`docs/architecture/commerce-platform.md`](docs/architecture/commerce-platform.md).
O contrato de autenticação e autorização está em
[`docs/architecture/authentication-and-authorization.md`](docs/architecture/authentication-and-authorization.md).
O contrato de isolamento no banco e migrations está em
[`docs/architecture/database-tenancy-and-migrations.md`](docs/architecture/database-tenancy-and-migrations.md).
O contrato inicial do Capability Mesh está em
[`docs/architecture/capability-mesh.md`](docs/architecture/capability-mesh.md).
A matriz responsiva validada está em
[`docs/quality/responsive-audit-2026-08-21.md`](docs/quality/responsive-audit-2026-08-21.md).

## Roadmap canônico

A sequência oficial de construção das experiências do cliente, dos domínios
Food Service, do motor financeiro e da conclusão do Control Plane está em
[`docs/product/roadmap-commerce-os-v2.md`](docs/product/roadmap-commerce-os-v2.md).

Os gates **S0–S13.1** consolidaram contratos, shells, autorização, catálogo,
Frente de Caixa, `Order Foundation` e Mesas & Comandas. `ServiceTable`,
`TableSession` e `Order` são contratos distintos, com concorrência,
idempotência, RLS, auditoria e interface operacional baseada somente em dados
persistidos. O **S8 — Checkout Negotiation e Payment Orchestrator** é a
autoridade server-side para snapshot, split, parcelas,
allocations e saldo restante. Pagamentos confirmados são preservados diante de
falha posterior; saldo zero não libera a mesa sem finalização explícita. O
S9 adiciona `ProviderTransaction`, adapters intercambiáveis, pareamento local
por segredo com hash, heartbeat/telemetria e reconciliação de estados
`PROCESSING`/`UNKNOWN`. A UI distingue cartão manual de TEF e mostra “não
configurado/offline” sem simular homologação. O **S10 — Dashem Channel Hub e
External Order Inbox** recebe, autentica, persiste, deduplica e normaliza pedidos
externos no mesmo `Order Engine`, sem fingir conexão com providers ainda não
homologados. O **S11 — Production Routing e KDS** adiciona pontos e regras
persistidos, dispatch idempotente, tickets por versão/operação e uma fila KDS
real com concorrência otimista, ator, dispositivo, auditoria e outbox. O
**S12 — Transferências e Comandas Avançadas** conserva quantidade e valor por
itens derivados, registra linhagem imutável, exige versões concorrentes e bloqueia
cobertura financeira/produção incompatível. O **S13 — Channel
Catalog e Marketplace Reconciliation** mantém identidade única do produto,
publicação versionada item a item e repasses separados da venda operacional. O
**S13.1 — Retaguarda Operacional do Tenant** separa configuração de operação:
Gestão cadastra ambientes, mesas, reservas, estoque, categorias, caixas, KDS e
impressoras; PDV e KDS não oferecem retorno administrativo. A atendente somente
opera mesas existentes, pode sinalizar impedimento e precisa confirmar uma
reserva identificada antes de abrir a sessão. Dispositivo e estrutura vinculada
nascem na mesma transação e todo ciclo de pausa/revogação permanece auditável. O
**S14 — Crediário e Receivables** acrescenta política de crédito versionada,
limite e exposição calculada sob lock, `Receivable`, allocation explícita da
negociação e ledger imutável. A venda a prazo e o título são gravados na mesma
transação; o valor financiado não cria `Payment` nem movimento de caixa. A
Gestão possui workspace real de crediário, protegido por permission e pela
capability `receivables`. O **S15 — Recebimentos, Cobrança e Renegociação**
adiciona liquidação multi-título pelo orquestrador, allocations com ajustes
explícitos, histórico de cobrança e acordos cujas parcelas permanecem ligadas
aos documentos originais. Retentativas não duplicam baixas e o principal nunca
é reescrito. O **S16 — Cash, Fiscal e Financial Reconciliation Completion**
completa o ciclo `OPEN → CLOSING → CLOSED` com versão concorrente, conferência
cega e saldo derivado exclusivamente do ledger. Movimentos carregam origem
idempotente; estorno preserva o pagamento confirmado e cria fato compensatório.
Tentativas fiscais permanecem no mesmo `FiscalDocument`, enquanto a conciliação
liga venda, negociação, recebível, caixa e fiscal e somente sinaliza diferenças.
O próximo gate canônico deste loop é o **S17 — Business Intelligence V1**.

## Trilha pendente: conclusão do Console Owner

O Console Owner já possui sua primeira operação real e continuará evoluindo em
paralelo, sem assumir a administração cotidiana da equipe dos clientes. O
Platform Owner administra tenants, contrato, plano, limites, capabilities,
onboarding, administrador contratual, segurança e saúde da plataforma.

O contrato funcional detalhado deste marco está em
[`docs/product/owner-console-operational.md`](docs/product/owner-console-operational.md).
Nenhuma métrica ou cliente será simulado: registros de teste percorrem o mesmo
modelo persistente e auditável usado por clientes comerciais.

### 1. Comunicação transacional

- manter temporariamente o Gmail Custom SMTP já validado no Supabase Auth;
- verificar `auth.dashem.tech` no Resend;
- publicar SPF, DKIM e DMARC;
- configurar o Resend como Custom SMTP do Supabase Auth;
- criar templates Dashem para convite, recuperação e confirmação;
- ajustar rate limits conforme a capacidade contratada;
- receber webhooks de entrega, bounce e complaint no backend;
- testar convite, expiração, recuperação, reenvio e troca de senha.

### 2. Segurança do Owner

- concluir o primeiro acesso de `dashemtech@gmail.com`;
- exigir senha forte e TOTP MFA;
- validar revogação de sessão e recuperação de conta;
- auditar toda ação privilegiada;
- remover ou ocultar provedores sociais ainda não configurados.

### 3. Console Owner

- concluir a ficha mestre persistida de clientes, contatos, matriz/filiais e contrato;
- dashboard de saúde da plataforma;
- leads e solicitações de acesso;
- criação, suspensão e reativação de tenants;
- criação de sites e definição de capabilities;
- evoluir o convite já implementado para reenvio, cancelamento e timeline de entrega;
- linha do tempo verificável de convites e recuperação;
- logs correlacionados de API, autenticação e entrega de e-mail;
- suporte assistido explícito, temporário e auditado;
- limites, planos e estado do onboarding;
- estados vazios, falhas e retries reais, sem dados hardcoded.

Primeira fundação implementada localmente: modelo cadastral, classificação de
teste/piloto/cliente, contato principal, endereço da matriz, planos armazenados
no banco e estados pausado/arquivado com mutações auditadas.

### 4. Piloto multi-tenant

- criar tenants de teste com slugs distintos;
- criar múltiplos sites por tenant;
- validar RBAC e escopo por site;
- executar testes negativos de isolamento;
- garantir que um operador nunca leia ou altere outro tenant;
- validar catálogo editável/importável e diferentes verticais;
- documentar onboarding e runbooks do helpdesk.

## Arquitetura técnica

- Frontend: React, TypeScript, Vite e Tailwind CSS
- API: FastAPI, SQLModel e Alembic canônico
- Banco: PostgreSQL
- Identity Provider: Supabase Auth
- E-mail transacional adotado: Resend
- Frontend cloud: Vercel
- Backend cloud: Render
- Ambiente local: Docker Compose

O repositório é um monorepo:

```text
backend/     API, serviços, modelos, migrations, scripts e testes
frontend/    aplicação React
docs/        decisões e contratos arquiteturais
```

## Execução local

### Backend e banco

Copie `.env.example` para `.env` e substitua os valores `change-me`.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

A API estará em `http://localhost:8002` e sua documentação em
`http://localhost:8002/docs`.

### Frontend

```powershell
Set-Location frontend
Copy-Item .env.example .env
npm ci
npm run dev
```

O frontend estará em `http://localhost:5173`.

## Validação

```powershell
python -m pytest backend/tests
Set-Location frontend
npm run build
```

O workflow em `.github/workflows/ci.yml` rejeita falhas de build, testes de
isolamento com PostgreSQL real e divergências entre modelos e migrations. O
gate do Alembic reconstrói um banco vazio, executa downgrade e novo upgrade e
finaliza com `alembic check`.

Com o backend no Docker:

```powershell
docker compose exec -T -e TEST_BASE_URL=http://127.0.0.1:8000 dashem-pos-backend python -m pytest tests
```

## Política de segurança

- Nunca versionar arquivos `.env` reais.
- Usar segredos diferentes em desenvolvimento, homologação e produção.
- Produção exige `AUTH_MODE=required`.
- O frontend recebe somente a chave Publishable do Supabase; `service_role` e
  credenciais SMTP nunca podem aparecer no navegador.
- O primeiro Platform Owner não é criado por cadastro público.
- Toda autorização é revalidada no backend; esconder uma rota no frontend não
  constitui controle de acesso.
- Filtros de ORM não constituem isolamento: tabelas de tenant e unidade devem
  ter RLS forçado e testes negativos no PostgreSQL.
- A aplicação nunca serve requisições com a autoridade proprietária do schema.
- Toda alteração de schema passa pelo Alembic; DDL de runtime é proibido.
- Links e tokens de autenticação nunca são armazenados integralmente em logs.
- Ações de suporte sobre tenants exigirão motivo, prazo e auditoria.
- Dados de demonstração não podem ser usados como dados de produção.

## Licença

Este repositório não possui licença de código aberto. Todos os direitos são
reservados.
