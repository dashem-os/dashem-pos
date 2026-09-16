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

Extended on 16/09/2026 (ADR-029 §1.2), before any code was born inside
app/modules: until then this test read only app/services and app/models, so a
module package would have looked modular while nothing guarded it. Three things
changed at once:

- imports are read from the syntax tree, not from a regex anchored at column
  zero — an import inside a function, split over lines or written relative to
  the package is coupling all the same;
- a service calling another module's service is checked, not only a service
  reading another module's model;
- code under app/modules/<domain>/ reaches another domain only through that
  domain's `contracts` module, and only in the allowed direction. A question
  that must look *up* goes through a port, as settlement already does.

The delivery layer — app/api, app/workers, app/core — is the composition root
and is deliberately not checked: it is where modules are wired, not a module.
"""

import ast
import re
from pathlib import Path
from typing import Optional

BACKEND = Path(__file__).resolve().parents[1]
MODELS = BACKEND / "app" / "models"
SERVICES = BACKEND / "app" / "services"
MODULES = BACKEND / "app" / "modules"

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
    # Quem fornece a mercadoria fica com a mercadoria: o vínculo é do
    # recebimento, e finanças pode ler catálogo quando precisar do favorecido.
    "supplier": "catalog",
    "order": "operation",
    "sale": "operation",
    "table_service": "operation",
    "transfer": "operation",
    "production": "operation",
    "payable": "finance",
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
    "catalog_storage": "catalog",
    "starter_catalog": "catalog",
    "media": "catalog",
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
# Ports: packages under app/modules that belong to no domain. Each names a
# question so that the side asking never reads the side answering. Any module
# may import a port; a port reaches only the domains listed here.
# ---------------------------------------------------------------------------
PORTS = {
    # O tenant consulta o que o Owner concedeu por aqui, e só por aqui (ADR-029 §1).
    "capabilities": {"owner"},
    # Contratos puros da governança do Owner: tipos, sem persistência.
    "governance": set(),
    # A pergunta que operation faz a finance sem ler a tabela dela (ADR-029 §1.1).
    "settlement": set(),
}

# The one Owner service a tenant module may call: ADR-029 §1 names it, next to
# capabilities, as the contract through which a tenant learns its rights.
OWNER_CONTRACT_SERVICES = {"contract_entitlement"}

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
    # "transfer -> negotiation" saiu em 05/09/2026: a regra continua, e passou a
    # ser perguntada ao módulo de finanças pela porta app/modules/settlement,
    # como este comentário pedia. É a primeira linha que a migração devolve.
}

# Service-to-service crossings that already existed when this was first checked,
# on 16 September 2026. Same rule: remove lines, never add them.
SERVICE_BASELINE = {
    # Cota de storage e de dispositivos é pergunta legítima ao Owner. Ela deveria
    # passar pela porta de governança, que já tem os tipos, em vez de importar o
    # serviço que a implementa.
    "catalog_storage -> storage_quota",
    "catalog_storage -> storage_reconciliation",
    "device -> quota_policy",
}


# ---------------------------------------------------------------------------
# Reading imports.
# ---------------------------------------------------------------------------
def _dotted_imports(path: Path, backend: Path = BACKEND) -> set[str]:
    """Every module a file imports, as a dotted path, wherever the import sits.

    `from package import name` resolves to `package.name` when the package is a
    directory, because the name may be a submodule — `from app.services import
    media_service` is a service import like any other.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = list(path.relative_to(backend).parent.parts)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                source = ".".join(base + ([node.module] if node.module else []))
            else:
                source = node.module or ""
            if source and (backend / Path(*source.split("."))).is_dir():
                found.update(f"{source}.{alias.name}" for alias in node.names)
            else:
                found.add(source)
    return found


def _model_file(dotted: str) -> Optional[str]:
    parts = dotted.split(".")
    return parts[2] if parts[:2] == ["app", "models"] and len(parts) > 2 else None


def _service_name(dotted: str) -> Optional[str]:
    parts = dotted.split(".")
    if parts[:2] == ["app", "services"] and len(parts) > 2 and parts[2].endswith("_service"):
        return parts[2][: -len("_service")]
    return None


def _module_path(dotted: str) -> tuple[Optional[str], list[str]]:
    parts = dotted.split(".")
    if parts[:2] == ["app", "modules"] and len(parts) > 2:
        return parts[2], parts[3:]
    return None, []


def _domain_of(dotted: str) -> Optional[str]:
    """Which domain an import lands in, or None for infrastructure and ports."""
    model = _model_file(dotted)
    if model is not None:
        return MODULE_OF_MODEL.get(model)
    service = _service_name(dotted)
    if service is not None:
        return MODULE_OF_SERVICE.get(service)
    package, _ = _module_path(dotted)
    return package if package in ALLOWED else None


def _crossing(origin: str, dotted: str) -> bool:
    """Would `origin` importing `dotted` cross a module boundary?"""
    model = _model_file(dotted)
    if model is not None:
        target = MODULE_OF_MODEL.get(model)
        return target is not None and target not in ALLOWED[origin]
    service = _service_name(dotted)
    if service is not None:
        target = MODULE_OF_SERVICE.get(service)
        if target is None or service in OWNER_CONTRACT_SERVICES:
            return False
        return target not in ALLOWED[origin]
    package, rest = _module_path(dotted)
    if package is None or package == origin or package in PORTS:
        return False
    if package not in ALLOWED:
        return True
    # Another domain: only in the allowed direction, and only its contracts.
    return package not in ALLOWED[origin] or rest[:1] != ["contracts"]


def _services(backend: Path):
    for path in sorted((backend / "app" / "services").glob("*_service.py")):
        service = path.name[: -len("_service.py")]
        origin = MODULE_OF_SERVICE.get(service)
        if origin is not None:
            yield path, service, origin


def _violations(backend: Path = BACKEND) -> set[str]:
    found = set()
    for path, service, origin in _services(backend):
        for dotted in _dotted_imports(path, backend):
            model = _model_file(dotted)
            target = MODULE_OF_MODEL.get(model) if model else None
            if target is not None and target not in ALLOWED[origin]:
                found.add(f"{service} -> {model}")
    return found


def _service_crossings(backend: Path = BACKEND) -> set[str]:
    found = set()
    for path, service, origin in _services(backend):
        for dotted in _dotted_imports(path, backend):
            called = _service_name(dotted)
            if called is None or called == service:
                continue
            if _crossing(origin, dotted):
                found.add(f"{service} -> {called}")
    return found


def _module_crossings(backend: Path = BACKEND) -> set[str]:
    """Imports made from inside app/modules, and from services into it.

    No baseline: these packages are new, and they are born guarded.
    """
    modules = backend / "app" / "modules"
    found = set()
    for path in sorted(modules.rglob("*.py")):
        relative = path.relative_to(modules)
        if len(relative.parts) == 1:
            continue
        package, where = relative.parts[0], relative.as_posix()
        for dotted in _dotted_imports(path, backend):
            if package in PORTS:
                target = _domain_of(dotted)
                if target is not None and target not in PORTS[package]:
                    found.add(f"{where} -> {dotted}")
            elif package in ALLOWED and _crossing(package, dotted):
                found.add(f"{where} -> {dotted}")
    for path, service, origin in _services(backend):
        for dotted in _dotted_imports(path, backend):
            if dotted.startswith("app.modules.") and _crossing(origin, dotted):
                found.add(f"services/{path.name} -> {dotted}")
    return found


def _undeclared_packages(backend: Path = BACKEND) -> set[str]:
    modules = backend / "app" / "modules"
    packages = {p.name for p in modules.iterdir() if p.is_dir() and p.name != "__pycache__"}
    return packages - set(ALLOWED) - set(PORTS)


def _class_module(backend: Path = BACKEND) -> dict[str, str]:
    """Which module defines each class, in app/models or in a domain package."""
    home = {}
    for path in (backend / "app" / "models").glob("*.py"):
        module = MODULE_OF_MODEL.get(path.stem)
        if module is None:
            continue
        for match in re.finditer(r"^class ([A-Za-z]+)\(", path.read_text(encoding="utf-8"), re.M):
            home[match.group(1)] = module
    modules = backend / "app" / "modules"
    for path in modules.rglob("*.py"):
        package = path.relative_to(modules).parts[0]
        if package not in ALLOWED:
            continue
        for match in re.finditer(r"^class ([A-Za-z]+)\(", path.read_text(encoding="utf-8"), re.M):
            home[match.group(1)] = package
    return home


# ---------------------------------------------------------------------------
# The rules.
# ---------------------------------------------------------------------------
def test_every_service_and_model_belongs_to_a_declared_module():
    """A file with no owner is how the map silently stops being true."""
    models = {p.stem for p in MODELS.glob("*.py") if p.stem != "__init__"}
    services = {p.name[: -len("_service.py")] for p in SERVICES.glob("*_service.py")}
    assert models - set(MODULE_OF_MODEL) == set(), "modelo sem módulo declarado"
    assert services - set(MODULE_OF_SERVICE) == set(), "serviço sem módulo declarado"


def test_every_module_package_is_a_domain_or_a_port():
    assert _undeclared_packages() == set(), (
        "Pacote em app/modules que não é domínio nem porta declarada"
    )


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


def test_no_new_service_calls_across_a_module_boundary():
    new = _service_crossings() - SERVICE_BASELINE
    assert new == set(), (
        "Serviço chamando serviço de outro módulo fora da direção permitida:\n  "
        + "\n  ".join(sorted(new))
        + "\n\nPergunte por uma porta em app/modules em vez de importar o serviço."
    )
    stale = SERVICE_BASELINE - _service_crossings()
    assert stale == set(), (
        "Estas chamadas não existem mais e devem sair do SERVICE_BASELINE:\n  "
        + "\n  ".join(sorted(stale))
    )


def test_module_packages_reach_other_domains_only_through_contracts():
    offenders = _module_crossings()
    assert offenders == set(), (
        "Import atravessando fronteira a partir de app/modules:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\nOutro domínio se alcança por app.modules.<domínio>.contracts, e só "
        "na direção permitida. Pergunta que olha para cima vai por uma porta."
    )


def test_no_tenant_module_reaches_into_the_owner_layer():
    """The hard rule, which has no baseline and never will.

    The Owner governs tenants — capabilities, contracts, limits, billing. A
    tenant-side service that reads an Owner table has erased the layer.
    """
    offenders = []
    for path, service, origin in _services(BACKEND):
        if origin in ("owner", "shared"):
            continue
        for dotted in _dotted_imports(path):
            model = _model_file(dotted)
            if model and MODULE_OF_MODEL.get(model) == "owner":
                offenders.append(f"{service} -> {model}")
    assert offenders == [], (
        "Serviço de tenant lendo tabela da camada Owner:\n  " + "\n  ".join(offenders)
    )


def test_no_orm_relationship_crosses_a_module_boundary():
    """The blind spot an audit found, closed.

    A `Relationship` names its target as a string, so an import scan never sees
    it. `Register.sessions` pointed at `CashSession` — identity reaching into
    finance — and passed every check while doing so. A relationship is coupling
    just like an import, and a forward reference is exactly how that coupling
    hides.
    """
    home = _class_module()
    pattern = re.compile(
        r"""(\w+):\s*(?:Optional\[|List\[)?["'](\w+)["']\]?\s*=\s*Relationship"""
    )
    sources = [(p.stem, MODULE_OF_MODEL.get(p.stem), p) for p in sorted(MODELS.glob("*.py"))]
    sources += [
        (p.relative_to(MODULES).as_posix(), p.relative_to(MODULES).parts[0], p)
        for p in sorted(MODULES.rglob("*.py"))
        if len(p.relative_to(MODULES).parts) > 1
    ]
    offenders = []
    for label, origin, path in sources:
        if origin not in ALLOWED:
            continue
        for field, target in pattern.findall(path.read_text(encoding="utf-8")):
            destination = home.get(target, "?")
            if destination not in ALLOWED[origin]:
                offenders.append(f"{label}.{field} -> {target} ({origin} -> {destination})")
    assert offenders == [], "Relacionamento ORM atravessando fronteira: " + "; ".join(
        sorted(offenders)
    )


# ---------------------------------------------------------------------------
# The guard, broken on purpose. Each rule above has to catch the crossing it
# exists for — and has to leave alone the legitimate import that looks like it.
# ---------------------------------------------------------------------------
def _write(root: Path, relative: str, source: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in path.relative_to(root).parents:
        if str(parent) != ".":
            (root / parent / "__init__.py").touch()
    path.write_text(source, encoding="utf-8")


def _synthetic_backend(root: Path) -> Path:
    _write(root, "app/models/order.py")
    _write(root, "app/models/payment.py")
    _write(root, "app/models/platform.py")
    _write(root, "app/services/contract_entitlement_service.py")
    _write(root, "app/services/storage_quota_service.py")
    _write(root, "app/modules/settlement/contracts.py")
    _write(root, "app/modules/operation/contracts.py")
    _write(root, "app/modules/finance/contracts.py")
    _write(root, "app/modules/operation/tables.py", (
        "from app.models.order import Order\n"
        "from app.modules.settlement.contracts import hold_on_items\n"
        "def later():\n"
        "    from app.models.payment import Payment\n"
    ))
    _write(root, "app/modules/operation/kitchen.py", (
        "from app.modules.finance.contracts import Charge\n"
    ))
    _write(root, "app/modules/finance/bridge/service.py", (
        "from app.models.order import Order\n"
        "from app.modules.operation.contracts import Port\n"
        "from app.modules.operation import tables\n"
        "from ..contracts import Own\n"
        "from . import models\n"
        "from app.services.contract_entitlement_service import resolve\n"
        "from app.services.storage_quota_service import (\n"
        "    measure,\n"
        ")\n"
    ))
    _write(root, "app/modules/channels/intake.py", (
        "import app.modules.finance.bridge.service\n"
    ))
    _write(root, "app/modules/capabilities/service.py", (
        "from app.models.platform import Plan\n"
        "from app.models.order import Order\n"
    ))
    _write(root, "app/modules/pricing/rules.py")
    _write(root, "app/services/order_service.py", (
        "from app.modules.finance.bridge.service import charge\n"
        "from app.modules.operation.tables import open_table\n"
    ))
    _write(root, "app/services/catalog_service.py", (
        "from app.services import contract_entitlement_service, storage_quota_service\n"
    ))
    return root


def test_the_guard_catches_what_it_exists_for_and_nothing_else(tmp_path):
    backend = _synthetic_backend(tmp_path)

    assert _module_crossings(backend) == {
        # an upward read hidden inside a function
        "operation/tables.py -> app.models.payment",
        # upward is upward, contracts or not: that question belongs to a port
        "operation/kitchen.py -> app.modules.finance.contracts",
        # downward, but into internals instead of contracts
        "finance/bridge/service.py -> app.modules.operation.tables",
        # an Owner service that is not the sanctioned contract, over three lines
        "finance/bridge/service.py -> app.services.storage_quota_service",
        # a sideways reach between two tenant domains
        "channels/intake.py -> app.modules.finance.bridge.service",
        # a port reaching past what it was declared to reach
        "capabilities/service.py -> app.models.order",
        # a flat service reaching into another domain's package
        "services/order_service.py -> app.modules.finance.bridge.service",
    }
    assert _undeclared_packages(backend) == {"pricing"}
    assert _service_crossings(backend) == {"catalog -> storage_quota"}
