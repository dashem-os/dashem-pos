"""The module map, enforced.

ADR-029. The roadmap has made modularity obligatory since its first section and
declares that "os limites modulares passam a valer imediatamente". Two modules
were created — capabilities and governance — and then twenty domains grew flat
under app/services and app/models, with nothing declaring which module owns
which table and nothing stopping any service from importing any model.

This test does not move a single file. It declares the map, states the allowed
direction of dependency, and freezes today's violations in a baseline. Existing
crossings stay listed and visible; a *new* one fails the build. That is what
changes the direction now instead of after a refactor nobody has time to finish.

Removing a line from BASELINE is how the migration advances. Adding one is not
allowed — it means the boundary was crossed again.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODELS = BACKEND / "app" / "models"
SERVICES = BACKEND / "app" / "services"

# ---------------------------------------------------------------------------
# The map: which module owns which model file.
# ---------------------------------------------------------------------------
MODULE_OF_MODEL = {
    # Infrastructure every module may use.
    "reliability": "shared",
    # The Owner layer: it governs tenants, it does not operate them.
    "platform": "owner",
    "owner_finance": "owner",
    "storage": "owner",
    "commercial_catalog": "owner",
    # Tenant domains.
    "identity": "identity",
    "device": "identity",
    "catalog": "catalog",
    "assortment": "catalog",
    "order": "operation",
    "sale": "operation",
    "table_service": "operation",
    "transfer": "operation",
    "production": "operation",
    "payment": "finance",
    "negotiation": "finance",
    "provider": "finance",
    "receivable": "finance",
    "reconciliation": "finance",
    "fiscal": "finance",
    "channel_hub": "channels",
    "channel_catalog": "channels",
    "bi": "insight",
    "intelligence": "insight",
}

MODULE_OF_SERVICE = {
    "reliability": "shared",
    "outbox_dispatch": "shared",
    "owner_finance": "owner",
    "commercial_offer": "owner",
    "contract_entitlement": "owner",
    "quota_policy": "owner",
    "storage_quota": "owner",
    "storage_reconciliation": "owner",
    "identity": "identity",
    "device": "identity",
    "operational_access": "identity",
    "operational_session": "identity",
    "catalog": "catalog",
    "assortment": "catalog",
    "inventory": "catalog",
    "starter_catalog": "catalog",
    "order": "operation",
    "sale": "operation",
    "table": "operation",
    "transfer": "operation",
    "production": "operation",
    "cash": "finance",
    "payment": "finance",
    "payment_audit": "finance",
    "negotiation": "finance",
    "provider": "finance",
    "receivable": "finance",
    "reconciliation": "finance",
    "fiscal": "finance",
    "channel_catalog": "channels",
    "channel_hub": "channels",
    "bi": "insight",
}

# ---------------------------------------------------------------------------
# The direction of dependency. A module may read its own models, plus these.
# Nothing points back up: operation never reaches into finance, and no tenant
# module ever touches the Owner layer's tables.
# ---------------------------------------------------------------------------
ALLOWED = {
    "shared": {"shared"},
    "identity": {"identity", "shared"},
    "catalog": {"catalog", "identity", "shared"},
    "operation": {"operation", "catalog", "identity", "shared"},
    "finance": {"finance", "operation", "catalog", "identity", "shared"},
    "channels": {"channels", "operation", "catalog", "identity", "shared"},
    # Insight is a read-side projection over everything; it writes to nobody.
    "insight": {"insight", "operation", "catalog", "identity", "finance", "channels", "shared"},
    # The Owner governs the tenant: it may name tenants and stores, never their
    # operation, catalogue, money or channels.
    "owner": {"owner", "identity", "shared"},
}

# ---------------------------------------------------------------------------
# Crossings that already exist on 4 September 2026. Each line is a debt, not a
# permission. Remove lines as the migration advances; never add one.
# ---------------------------------------------------------------------------
BASELINE = {
    # As três restantes são acoplamento real, a resolver por contrato de módulo:
    #
    # o dispositivo consulta o ponto de produção para saber se um KDS tem destino
    "device -> production",
    # a venda antiga referencia o pagamento diretamente, herança do fluxo pré-S8
    "sale -> payment",
    # a transferência recusa mover item já coberto por PaymentAllocation, que é
    # regra legítima e deveria ser perguntada ao módulo de finanças, não lida
    # direto da tabela dele
    "transfer -> negotiation",
}


def _model_imports(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    return set(re.findall(r"^from app\.models\.([a-z_]+)", source, re.MULTILINE))


def _violations() -> set[str]:
    found = set()
    for path in sorted(SERVICES.glob("*_service.py")):
        service = path.name[: -len("_service.py")]
        origin = MODULE_OF_SERVICE.get(service)
        if origin is None:
            continue
        for model in _model_imports(path):
            target = MODULE_OF_MODEL.get(model)
            if target is None:
                continue
            if target not in ALLOWED[origin]:
                found.add(f"{service} -> {model}")
    return found


def test_every_service_and_model_belongs_to_a_declared_module():
    """A file with no owner is how the map silently stops being true."""
    models = {p.stem for p in MODELS.glob("*.py") if p.stem != "__init__"}
    services = {p.name[: -len("_service.py")] for p in SERVICES.glob("*_service.py")}
    assert models - set(MODULE_OF_MODEL) == set(), "modelo sem módulo declarado"
    assert services - set(MODULE_OF_SERVICE) == set(), "serviço sem módulo declarado"


def test_no_new_crossing_of_a_module_boundary():
    new = _violations() - BASELINE
    assert new == set(), (
        "Novas travessias de fronteira de módulo:\n  "
        + "\n  ".join(sorted(new))
        + "\n\nUse o contrato do módulo dono em vez de importar o modelo dele."
    )


def test_the_baseline_does_not_grow_stale():
    """A line that no longer describes reality must leave the baseline.

    Otherwise the debt list slowly becomes fiction and stops meaning anything.
    """
    stale = BASELINE - _violations()
    assert stale == set(), (
        "Estas travessias não existem mais e devem sair do BASELINE:\n  "
        + "\n  ".join(sorted(stale))
    )


def test_no_tenant_module_reaches_into_the_owner_layer():
    """The hard rule, which has no baseline and never will.

    The Owner governs tenants — capabilities, contracts, limits, billing. A
    tenant-side service that reads an Owner table has erased the layer.
    """
    offenders = []
    for path in sorted(SERVICES.glob("*_service.py")):
        service = path.name[: -len("_service.py")]
        origin = MODULE_OF_SERVICE.get(service)
        if origin in (None, "owner", "shared"):
            continue
        for model in _model_imports(path):
            if MODULE_OF_MODEL.get(model) == "owner":
                offenders.append(f"{service} -> {model}")
    assert offenders == [], (
        "Serviço de tenant lendo tabela da camada Owner:\n  " + "\n  ".join(offenders)
    )
