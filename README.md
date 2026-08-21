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
- domínio comercial existente do PDV preservado durante a evolução arquitetural.

### Ainda não pronto para produção

- o SMTP padrão do Supabase foi rejeitado para qualquer fluxo real da Dashem;
- o Resend ainda precisa ser configurado e validado com domínio próprio;
- o primeiro acesso do Owner precisa ser retestado de ponta a ponta após o Resend;
- Google e Microsoft devem ficar ocultos até seus provedores OAuth estarem
  configurados e testados;
- o Console Owner ainda precisa alcançar o nível operacional definido abaixo;
- provisionamento, onboarding e isolamento de tenants precisam de testes
  negativos completos antes do primeiro piloto;
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

## Próximo marco: Console Owner operacional

Quando o desenvolvimento for retomado, o objetivo imediato não será ampliar o
PDV. Primeiro deixaremos o Console Owner profissional e plenamente operacional
para testar o ciclo de vida dos tenants.

### 1. Comunicação transacional

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

- dashboard de saúde da plataforma;
- leads e solicitações de acesso;
- criação, suspensão e reativação de tenants;
- criação de sites e definição de capabilities;
- convite de Owner/Admin do tenant;
- linha do tempo verificável de convites e recuperação;
- logs correlacionados de API, autenticação e entrega de e-mail;
- suporte assistido explícito, temporário e auditado;
- limites, planos e estado do onboarding;
- estados vazios, falhas e retries reais, sem dados hardcoded.

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
- API: FastAPI, SQLModel e Alembic
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
- Links e tokens de autenticação nunca são armazenados integralmente em logs.
- Ações de suporte sobre tenants exigirão motivo, prazo e auditoria.
- Dados de demonstração não podem ser usados como dados de produção.

## Licença

Este repositório não possui licença de código aberto. Todos os direitos são
reservados.
