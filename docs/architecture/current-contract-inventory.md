# Inventário baseline de contratos e estados — S0

Data do snapshot: 2026-08-23. Este documento registra o ponto de partida antes do
refactoring estrutural. A fonte executável continua sendo OpenAPI, modelos,
migrations e testes.

## Superfícies atuais

| Superfície | Contratos principais | Estado atual |
|---|---|---|
| Sistema | `GET /health` | saúde básica do processo |
| Identidade | `/api/v1/identity/me`, tenants, stores, memberships | JWT/Supabase, membership e contexto |
| Control | overview, health, tenant profile/lifecycle/subscription/capabilities/stores/access | operacional e persistido |
| Catálogo | categories, products, prices | CRUD parcial; listas ainda não paginadas |
| Estoque | adjust, balance, movements | ledger + saldo, concorrência protegida |
| Venda | customers, sales, items, discount, cancel, checkout | `Sale` direta com snapshots |
| Caixa | registers, sessions, movements | abertura, sangria, reforço e fechamento |
| Pagamento | create, confirm, list | parcial/split e idempotência de confirmação |
| Fiscal | issue, cancel, get | gateway e estados fiscais simuláveis |
| Capability | `GET /api/v1/capabilities/effective` | entitlement de produto; não é permission |

## Evolução validada até S13.1

| Domínio | Contrato canônico atual |
|---|---|
| Autorização | Permission Engine contextual; capability e permission avaliadas no servidor |
| Catálogo | `SellableProduct` paginado com preço, saldo, mínimo, margem, categoria e acesso rápido persistido |
| COUNTER | operação recuperável por store, terminal e operador; modos COUNTER/TAKEAWAY e conectividade explícita |
| Order | agregado separado de Sale; comandos de item idempotentes, snapshots e outbox transacional |
| Mesas e comandas | `ServiceTable`, `TableSession` e `Order` separados; sessão multi-comanda, projeção consolidada, concorrência e RLS |
| Retaguarda do tenant | Gestão configura catálogo, estoque, ambientes, mesas, reservas, terminais e produção; POS/KDS não elevam para Gestão |
| Reservas e impedimentos | `TableReservation` identificada e `ServiceTable` bloqueável com motivo; abertura reservada exige confirmação explícita |
| Dispositivos | `OperationalDevice` provisiona POS/KDS/impressora com vínculo transacional, heartbeat e revogação auditável |

## Máquinas de estado protegidas

### Tenant

`PROVISIONING → TRIAL → ACTIVE → PAUSED/SUSPENDED → CANCELED → ARCHIVED`.
Alterações do Control exigem motivo, AAL2 e auditoria.

### Membership

`INVITED → ACTIVE → SUSPENDED/REVOKED`. Acesso depende ainda do escopo de tenant
e store; platform membership não concede acesso implícito ao Commerce Plane.

### Sale

`DRAFT → CHECKOUT → AWAITING_PAYMENT → PAID → COMPLETED`, com `CANCELED` em
transições permitidas. Preço e identidade do produto são snapshots no item.

### CashSession e Payment

Caixa: `OPEN → CLOSED`. Pagamento: `PENDING → CONFIRMED/FAILED/REFUNDED`.
Pagamento em dinheiro exige sessão aberta e gera movimento no ledger.

### FiscalDocument

`NOT_REQUIRED/PENDING → AUTHORIZED/REJECTED/CONTINGENCY → CANCELED` conforme o
gateway. A finalização comercial respeita o gate fiscal configurado.

### ServiceTable e TableSession

Mesa física: `AVAILABLE/OCCUPIED/RESERVED/BLOCKED`. Atendimento:
`OPEN → IN_SERVICE → PARTIALLY_PAID/CLOSING → CLOSED`, com `CANCELED` quando
permitido. A mesa só volta a `AVAILABLE` por comando explícito e uma sessão pode
agrupar várias comandas (`Order`).

## Dívidas explicitamente não promovidas a contrato

- alternância Gestão/PDV por estado global;
- seleção automática do primeiro tenant/store/register quando existem vários;
- RBAC grosso por papel, método e prefixo;
- catálogo carregado por produtos + preços + saldo N+1;
- primeiros seis produtos tratados como acesso rápido;
- alerta visual de estoque em valor fixo;
- categoria inferida de descrição;
- diagnóstico técnico exposto no Gestão.

Esses comportamentos estão inventariados para remoção nos S1–S4 e não devem ser
copiados para novos módulos.
