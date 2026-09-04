"""What the backend offers, and what the product can actually reach.

The confrontation audit of 4 September 2026 kept finding the same shape, sprint
after sprint: models, service, endpoint and a green test, with no way for a
person to get there. S16 implements the two-phase cash close, blind count and
divergence reason, and proves them in `test_s16_financial_reconciliation.py` —
and `begin-close` and `finalize-close` have no function in the API client at
all. S13 has six write endpoints for channel publication and marketplace
settlement; the client exposes only the two reads. The fiscal contingency modal
promised an automatic retransmission over a `retry` endpoint the browser could
not call.

The roadmap's own ruler, section 10 item 7, says "implementado" means UI + API +
persistence + authorization + tests. Nothing measured the UI half. The frontend
suite matches strings against source text, so `assert.match(api, /updateOperationalDevice/)`
passes whether or not a screen ever calls it.

This test measures the gap in both directions and freezes today's number:

  * a route no client function reaches — the backend built a door with no handle;
  * a client function no component calls — a handle attached to no door.

Like `test_module_boundaries.py`, this declares the map, freezes the debt in a
baseline and fails on anything new. A line removed from a baseline is how the
product catches up with its own backend. A line that stopped being true must
leave, so the list never becomes fiction.
"""

import re
from pathlib import Path

from app.main import app

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
FRONTEND_API = FRONTEND / "services" / "api.ts"

# ---------------------------------------------------------------------------
# The map: which module owns each surface, in the vocabulary of ADR-029. The
# first segment after /api/v1 names the surface.
# ---------------------------------------------------------------------------
MODULE_OF_SURFACE = {
    "identity": "identity",
    "team": "identity",
    "operational-access": "identity",
    "devices": "identity",
    "catalog": "catalog",
    "inventory": "catalog",
    "orders": "operation",
    "sales": "operation",
    "tables": "operation",
    "transfers": "operation",
    "production": "operation",
    "cash": "finance",
    "payments": "finance",
    "fiscal": "finance",
    "negotiations": "finance",
    "providers": "finance",
    "receivables": "finance",
    "reconciliations": "finance",
    "channels": "channels",
    "channel-catalog": "channels",
    "management": "insight",
    # The Owner layer governs tenants. `capabilities` sits here because it reads
    # the Owner's grant — app.models.platform and contract_entitlement — and is
    # the contract surface ADR-029 §1 tells the tenant to consult.
    "control": "owner",
    "storage": "owner",
    "commercial-requests": "owner",
    "capabilities": "owner",
}

# ---------------------------------------------------------------------------
# Routes no browser will ever call, because the caller is another machine.
# These are not debt and never shrink: a marketplace posts to the webhook, the
# TEF bridge reports its own heartbeat and its transaction results.
# ---------------------------------------------------------------------------
NOT_A_BROWSER_SURFACE = {
    "POST /api/v1/channels/webhooks",
    "POST /api/v1/control/finance/provider/webhooks/{provider}",
    "POST /api/v1/providers/bridge/terminals/{terminal_id}/heartbeat",
    "POST /api/v1/providers/bridge/terminals/{terminal_id}/transactions/{transaction_id}/result",
}

# ---------------------------------------------------------------------------
# Routes the product cannot reach on 4 September 2026. Each line is a feature
# that exists on the server and does not exist for the person using it.
# ---------------------------------------------------------------------------
UNREACHABLE = {
    # identity — the device heartbeat has no sender, yet the Gestão device
    # screen shows "Presentes agora · heartbeat nos últimos 90 segundos".
    "POST /api/v1/devices/{device_id}/heartbeat",
    "GET /api/v1/identity/memberships",
    "POST /api/v1/identity/memberships",
    "GET /api/v1/identity/users",
    "POST /api/v1/identity/users",
    # catalog — combos and modifiers are modelled and cannot be registered. The
    # product screen only patches: removing a product is API-only.
    "POST /api/v1/catalog/combos",
    "POST /api/v1/catalog/modifier-groups",
    "POST /api/v1/catalog/modifiers",
    "POST /api/v1/catalog/products/{product_id}/modifier-groups",
    "DELETE /api/v1/catalog/products/{product_id}",
    # operation — S12: joining two tables and reading transfer lineage happen
    # only by API. Only /transfers/items reached the client.
    "POST /api/v1/production/orders/{order_id}/dispatch",
    "GET /api/v1/transfers",
    "POST /api/v1/transfers/merge",
    # finance — S16: the two-phase close and the tenant refund are proven by
    # tests and unreachable from the product. The fiscal retry left this list on
    # 4 September 2026, when the contingency modal started calling it.
    "POST /api/v1/cash/sessions/{session_id}/begin-close",
    "POST /api/v1/cash/sessions/{session_id}/finalize-close",
    "POST /api/v1/negotiations/intents/{intent_id}/fail",
    "POST /api/v1/payments/{payment_id}/refund",
    "POST /api/v1/providers/transactions/{transaction_id}/reconcile",
    "POST /api/v1/receivables/collection-events",
    "POST /api/v1/receivables/negotiations/{negotiation_id}/issue",
    "POST /api/v1/receivables/{receivable_id}/reverse",
    # an agreement can be created and cannot be read back: only POST reached the client
    "GET /api/v1/receivables/agreements",
    # channels — S13: ChannelHubWorkspace reads offers and settlements. Every
    # write — mapping, offer, publication, result, settlement payment — is API
    # only, so the screen is a window with no handle.
    "POST /api/v1/channel-catalog/mappings",
    "POST /api/v1/channel-catalog/offers",
    "POST /api/v1/channel-catalog/publications",
    "POST /api/v1/channel-catalog/publications/{batch_id}/results",
    "POST /api/v1/channel-catalog/settlements/{settlement_id}/payments",
    "POST /api/v1/channels/orders/{order_id}/outbound",
    # the client reads settlements and cannot open one
    "POST /api/v1/channel-catalog/settlements",
    # insight
    "GET /api/v1/management/bi/formulas",
    # owner — the Control plane carries most of the debt: pilots, incidents,
    # hardening runs, contracts and storage sources have endpoints and no console.
    "GET /api/v1/control/finance/collections/events",
    "POST /api/v1/control/finance/collections/events",
    "GET /api/v1/control/finance/payments/{payment_id}",
    "POST /api/v1/control/finance/payments/{payment_id}/reconcile",
    "GET /api/v1/control/finance/projections/{metric_date}",
    "POST /api/v1/control/hardening/runs",
    "GET /api/v1/control/hardening/runs/{run_id}",
    "PUT /api/v1/control/hardening/runs/{run_id}/evidence/{check_key}",
    "POST /api/v1/control/incidents",
    "PATCH /api/v1/control/incidents/{incident_id}",
    "PATCH /api/v1/control/leads/{lead_id}",
    # the console lists leads and cannot create one
    "POST /api/v1/control/leads",
    "GET /api/v1/control/pilots",
    "POST /api/v1/control/pilots",
    "GET /api/v1/control/pilots/{pilot_id}",
    "PATCH /api/v1/control/pilots/{pilot_id}",
    "POST /api/v1/control/pilots/{pilot_id}/incidents",
    "POST /api/v1/control/pilots/{pilot_id}/observations",
    "GET /api/v1/control/profiles",
    "PATCH /api/v1/control/support/{grant_id}",
    "POST /api/v1/control/tenants/{tenant_id}/contracts",
    "PUT /api/v1/control/tenants/{tenant_id}/onboarding/{key}",
    "POST /api/v1/control/tenants/{tenant_id}/profiles/{revision_id}/apply",
    "POST /api/v1/control/tenants/{tenant_id}/support",
    "GET /api/v1/control/tenants/{tenant_id}/workspace",
    "GET /api/v1/storage/platform/tenants/{tenant_id}/measurements",
    "GET /api/v1/storage/platform/tenants/{tenant_id}/sources",
    "POST /api/v1/storage/platform/tenants/{tenant_id}/sources",
}

# ---------------------------------------------------------------------------
# The other direction: client functions no component calls. Some are the client
# half of an unbuilt screen; others are leftovers of a refactor. Either way the
# product does not use them, and a growing list means the client is drifting
# ahead of the interface again.
# ---------------------------------------------------------------------------
ORPHAN_CLIENT_FUNCTIONS = {
    "cancelFiscalDocument",
    "cancelOrderItem",
    "createOrder",
    "createPlatformStore",
    "createProductionPoint",
    "createRegister",
    "createStore",
    "createTenant",
    "deleteTenantStorageObject",
    "fetchCashSessions",
    "fetchInventoryBalance",
    "fetchOrders",
    "fetchProductPrices",
    "fetchReconciliations",
    "getCheckoutNegotiation",
    "getFiscalDocument",
    "getOrder",
    "getSale",
    "invitePlatformTenantUser",
    "signTenantStorageDownload",
    "updateOrderItem",
    "updatePlatformStore",
    "updatePlatformTenantAccess",
    "updateProductionPoint",
    "updateRegister",
    "updateTenantCapability",
    "updateTenantSubscription",
    "uploadTenantStorageObject",
}


def _collapse(path: str) -> str:
    """`/objects/*/*/signed-url` and `/objects/*/signed-url` are one shape.

    The client builds some paths with a helper that fills several parameters in
    a single interpolation, so consecutive placeholders must read as one.
    """
    while "*/*" in path:
        path = path.replace("*/*", "*")
    return path


def _client_calls() -> set[tuple[str, str]]:
    """Every call the client makes, as (verb, shape).

    The verb is not decoration. A first version of this gate compared only the
    URL shape and reported a route as reached whenever *any* call touched the
    same path — so `POST /channel-catalog/settlements` counted as built because
    the client has a `GET` on it, and four routes hid behind their own siblings.
    `fetch` without an explicit `method` is a GET.
    """
    source = FRONTEND_API.read_text(encoding="utf-8")
    calls = set()
    for match in re.finditer(r"\$\{API_BASE_URL\}([^`]*)`", source):
        # `${...}` may itself contain braces: storageObjectPath(bucket, path).
        without_holes = re.sub(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "*", match.group(1))
        shape = _collapse(without_holes.split("?")[0])
        window = source[match.end(): match.end() + 400]
        next_call = window.find("fetch(")
        if next_call != -1:
            window = window[:next_call]
        verb = re.search(r"method:\s*'([A-Z]+)'", window)
        calls.add((verb.group(1) if verb else "GET", shape))
    return calls


def _route_shape(path: str) -> str:
    return _collapse(re.sub(r"\{[^}]+\}", "*", path))


def _routes() -> list[tuple[str, str]]:
    found = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in operations:
            if method.upper() in ("HEAD", "OPTIONS"):
                continue
            found.append((method.upper(), path))
    return found


def _unreachable() -> set[str]:
    calls = _client_calls()
    found = set()
    for method, path in _routes():
        shape = _route_shape(path)
        if (method, shape) in calls or (method, f"{shape}*") in calls:
            continue
        found.add(f"{method} {path}")
    return found


def _orphans() -> set[str]:
    source = FRONTEND_API.read_text(encoding="utf-8")
    exported = set(re.findall(r"export async function ([A-Za-z0-9_]+)", source))
    consumers = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FRONTEND.rglob("*")
        if path.suffix in (".ts", ".tsx") and path != FRONTEND_API
    )
    return {name for name in exported if not re.search(rf"\b{name}\b", consumers)}


def test_every_surface_belongs_to_a_declared_module():
    """A surface with no module is how the map silently stops being true."""
    surfaces = {path.split("/")[3] for _, path in _routes()}
    assert surfaces - set(MODULE_OF_SURFACE) == set(), "superfície sem módulo declarado"


def test_no_new_route_is_unreachable_from_the_product():
    new = _unreachable() - UNREACHABLE - NOT_A_BROWSER_SURFACE
    by_module = sorted(
        f"[{MODULE_OF_SURFACE.get(entry.split('/')[3], '?')}] {entry}" for entry in new
    )
    assert new == set(), (
        "Rotas novas que nenhuma tela alcança:\n  "
        + "\n  ".join(by_module)
        + "\n\nUm endpoint sem função no cliente não é sprint entregue: é backend "
        "pronto e tela ausente. Construa a jornada ou declare a rota como "
        "superfície de máquina."
    )


def test_the_unreachable_baseline_does_not_grow_stale():
    """A line that no longer describes reality must leave, or the debt is fiction."""
    live = _unreachable()
    declared = UNREACHABLE | NOT_A_BROWSER_SURFACE
    existing = {f"{method} {path}" for method, path in _routes()}

    reached = sorted(UNREACHABLE - live)
    assert reached == [], (
        "Estas rotas já são alcançáveis e devem sair de UNREACHABLE:\n  "
        + "\n  ".join(reached)
    )

    gone = sorted(declared - existing)
    assert gone == [], (
        "Estas rotas não existem mais e devem sair da declaração:\n  " + "\n  ".join(gone)
    )


def test_no_new_client_function_is_orphaned():
    new = sorted(_orphans() - ORPHAN_CLIENT_FUNCTIONS)
    assert new == [], (
        "Funções novas do cliente que nenhum componente chama:\n  "
        + "\n  ".join(new)
        + "\n\nO cliente voltou a andar na frente da interface."
    )


def test_the_orphan_baseline_does_not_grow_stale():
    adopted = sorted(ORPHAN_CLIENT_FUNCTIONS - _orphans())
    assert adopted == [], (
        "Estas funções ganharam consumidor ou deixaram de existir, e devem sair "
        "de ORPHAN_CLIENT_FUNCTIONS:\n  " + "\n  ".join(adopted)
    )
