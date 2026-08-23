# ADR-002 — Capability e Permission têm responsabilidades diferentes

- Status: aceito
- Data: 2026-08-23
- Decisores: Dashem Tech

## Contexto

O Dashem precisa simultaneamente limitar o que foi contratado pelo tenant e o que
cada pessoa pode fazer. Usar papéis ou capabilities para ambas as decisões cria
acesso excessivo e impede planos comerciais modulares.

## Decisão

- `Capability` representa produto contratado e limites: módulos, canais,
  integrações e capacidades operacionais concedidas ao tenant.
- `Permission` representa ação humana autorizada dentro de um contexto, por
  exemplo `catalog.update`, `sale.discount` ou `cash.close`.
- `RoleProfile` agrupa permissions como conveniência administrativa, mas não é a
  decisão final de autorização.
- A autorização efetiva é sempre calculada no servidor por:

```text
identidade válida
AND membership ativa
AND tenant/store/terminal autorizados
AND capability/entitlement ativo e dentro do limite
AND permission efetiva
```

O frontend recebe o resultado efetivo para montar a experiência, mas ocultar um
controle nunca substitui a negação do backend.

## Fronteiras administrativas

O Platform Owner contrata, concede ou revoga capabilities e limites, administra
o ciclo de vida do tenant e entrega o primeiro administrador contratual. O Tenant
Administrator cria a equipe e administra seus perfis/permissions dentro desses
limites. O Platform Owner não opera a equipe cotidiana do cliente.

## Consequências

Planos podem evoluir sem reescrever RBAC, e perfis podem evoluir sem mudar o
contrato comercial. Toda decisão passa a ser auditável. O RBAC atual por papel e
prefixo de rota é uma compatibilidade temporária e será substituído no S2.
