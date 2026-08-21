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

## Segurança

- Nunca versione arquivos `.env` reais.
- Use segredos diferentes em desenvolvimento, homologação e produção.
- Configure `DATABASE_URL`, `SECRET_KEY` e `VITE_API_URL` nos provedores de hospedagem.
- Os dados de demonstração não devem ser usados em produção.

## Licença

Este repositório não possui licença de código aberto. Todos os direitos são reservados.
