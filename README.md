# Dashem POS

Plataforma experimental de ponto de venda e gestão comercial da Dashem.

> **Estado do projeto:** protótipo técnico em desenvolvimento. Não está pronto para uso em produção ou comercialização.

## Arquitetura atual

- Frontend: React, TypeScript, Vite e Tailwind CSS
- API: FastAPI e SQLModel
- Banco de dados: PostgreSQL
- Ambiente local: Docker Compose

O repositório é um monorepo:

```text
backend/     API, serviços, modelos, migrações e testes
frontend/    aplicação React
```

## Arquitetura alvo

A evolução multi-tenant, multi-site, omnichannel e agent-ready está registrada
em [`docs/architecture/commerce-platform.md`](docs/architecture/commerce-platform.md).
O contrato implementado de autenticação Supabase e autorização do backend está
em [`docs/architecture/authentication-and-authorization.md`](docs/architecture/authentication-and-authorization.md).
O documento define os limites do Control Plane, Commerce Plane e Intelligence
Plane, além dos invariantes que novas implementações devem respeitar.

## Execução local

### 1. Configuração do backend e banco

Copie `.env.example` para `.env` e substitua todos os valores `change-me`.

No PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

A API ficará disponível em `http://localhost:8002` e a documentação em
`http://localhost:8002/docs`.

### 2. Configuração do frontend

```powershell
Set-Location frontend
Copy-Item .env.example .env
npm ci
npm run dev
```

O frontend ficará disponível em `http://localhost:5173`.

## Validação

Com o ambiente Docker em execução:

```powershell
python -m pytest backend/tests
Set-Location frontend
npm run build
```

Dentro do container do backend, aponte a suíte para a porta interna:

```powershell
docker compose exec -T -e TEST_BASE_URL=http://127.0.0.1:8000 dashem-pos-backend python -m pytest tests
```

## Segurança

- Nunca versione arquivos `.env` reais.
- Use segredos diferentes em desenvolvimento, homologação e produção.
- Configure `DATABASE_URL`, `SECRET_KEY` e `VITE_API_URL` nos provedores de hospedagem.
- Em produção configure `AUTH_MODE=required`, `SUPABASE_URL` e
  `SUPABASE_JWT_AUDIENCE=authenticated` no backend.
- No frontend configure `VITE_SUPABASE_URL` e `VITE_SUPABASE_PUBLISHABLE_KEY`.
  Nunca exponha a chave `service_role` em variáveis Vite ou no navegador.
- O primeiro Console Owner não é criado por cadastro público. Crie ou convide
  o usuário no Supabase Auth e vincule seu UUID com
  `python -m app.scripts.provision_access`. O procedimento completo está no
  contrato de autenticação acima.
- As rotas `/login` e `/owner` usam o mesmo domínio da aplicação. A decisão de
  destino é feita pela identidade e pelas autorizações retornadas pelo backend.
- Em bancos gerenciados pequenos, ajuste `DB_POOL_SIZE` e `DB_MAX_OVERFLOW`
  conforme o limite de conexões do provedor.
- Os dados de demonstração não devem ser usados em produção.

## Licença

Este repositório não possui licença de código aberto. Todos os direitos são reservados.
