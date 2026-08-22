# Capability Mesh contract

Status: first executable contract implemented.

## Purpose

Dashem does not build a paper-shop POS, a QSR POS and a supermarket POS as
forks. It builds a Commerce Core plus versioned capabilities whose dependencies
form a directed graph. Operational UX is composed from the effective graph for
the tenant, site and terminal.

```text
Capability definition (product contract)
        |
        +-- dependency edges
        |
        +-- commercial profile (optional bundle)
        |
        +-- tenant entitlement and contract limits
        |
        +-- site override
        v
Effective capability set for the current context
```

## Code contract

Immutable contracts live in `app/modules/capabilities` and contain:

- stable key;
- semantic version;
- scope: tenant, store or terminal;
- required capabilities;
- configuration contract.

The registry rejects unknown keys and dependency cycles. Dependency resolution
is deterministic and returns requirements before dependants. Database
definitions and edges are seeded by Alembic so the persisted graph and source
contract start from the same revision.

## Persistence contract

- `capability_definitions`: versioned product vocabulary;
- `capability_dependencies`: graph edges;
- `capability_profiles`: optional commercial/vertical bundles;
- `capability_profile_items`: bundle membership and defaults;
- `tenant_capabilities`: contractual entitlement, status, limits and config;
- `store_capability_overrides`: site-specific enablement/configuration.

Commercial profiles are data, not hardcoded assumptions. No paper-shop, QSR or
supermarket profile is automatically granted until the commercial model is
approved. Site overrides cannot grant a capability that the tenant contract
does not entitle.

## Module boundary

The current backend remains a modular monolith. A capability contract controls
availability; it is not permission, billing or a feature flag by itself.

Every capability implementation must eventually provide:

- domain commands and queries;
- permission requirements;
- persisted events and audit rules;
- configuration schema and validation;
- dependency declaration;
- health/diagnostic contribution;
- UI contribution points;
- negative tenant/site tests.

This contract is the extraction boundary for future services, not a reason to
create a distributed system prematurely.
