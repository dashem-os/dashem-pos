# Database tenancy and migration contract

Status: implemented foundation; mandatory for every new persistence module.

## Security boundary

Dashem uses a shared PostgreSQL schema with isolation enforced by the database,
not only by ORM filters. Every tenant-owned table has Row Level Security (RLS)
enabled and forced. Application connections assume `dashem_runtime`, a
`NOLOGIN`, `NOSUPERUSER`, `NOINHERIT` and `NOBYPASSRLS` role.

The migration/schema-owner credential and the runtime authority are distinct:

```text
DATABASE_ADMIN_URL  -> Alembic only; owns schema changes
DATABASE_URL        -> application pool; assumes dashem_runtime on every checkout
RUNTIME_DB_ROLE     -> dashem_runtime
```

When `DATABASE_ADMIN_URL` is absent, Alembic temporarily falls back to
`DATABASE_URL` for compatibility. Production should configure a dedicated
migration connection and never expose it to request-serving code.

This is database-enforced shared-schema isolation. It prevents a forgotten
`WHERE tenant_id = ...` from becoming a disclosure. It is not the same as a
database-per-tenant topology; physical database isolation remains an optional
future tier for contractual or regulatory requirements.

## Transaction context

Before a repository or service accesses tenant data, the authorization layer
sets transaction-local PostgreSQL settings:

- `app.platform_access`;
- `app.tenant_id`;
- `app.store_id`;
- `app.user_id`.

Policies fail closed when the required context is missing. The session stores
the authorized scope and reapplies it whenever a service commits and begins a
new transaction. Cross-tenant platform access is opened only after platform
RBAC succeeds; workers must also request platform or tenant scope explicitly.
The pool checkout hook reasserts `SET ROLE dashem_runtime` on every lease;
protecting only newly-created connections is insufficient because a driver can
reset role state when a connection returns to the pool.

## Tenant and site semantics

- tenant-owned rows require the active `tenant_id`;
- site-owned rows additionally require the active `store_id`;
- a missing store context means an authorized tenant-wide operation;
- `store_id IS NULL` means deliberately tenant-wide data, not an unknown site;
- tenant catalog entities may be shared by sites;
- prices, inventory, registers, cash, orders, payments, fiscal records and
  operational events are site-scoped;
- sale lines inherit their site boundary from their parent sale inside RLS.

New tables must declare their scope in the same migration that creates them.
A tenant or site table without an RLS policy is a CI-blocking defect.

## Alembic is canonical

Alembic is the only schema authority. Runtime `create_all`, ad-hoc startup DDL
and a second migration mechanism are prohibited.

The CI migration gate performs:

1. upgrade from an empty database to `head`;
2. downgrade to `base`;
3. rebuild to `head`;
4. `alembic check` against fully imported SQLModel metadata.

The API starts only after migrations succeed. A later production hardening
step should move migrations from the web-service entrypoint to a one-off
release job so schema ownership never exists in the serving process.

## Required tests

Each persistence module must include negative PostgreSQL tests for:

- tenant A cannot see or mutate tenant B;
- site A cannot see or mutate sibling site B operational data;
- missing context sees no tenant data;
- tenant users cannot activate platform scope;
- platform access is explicit and audited;
- indirect child records inherit the correct site boundary.
