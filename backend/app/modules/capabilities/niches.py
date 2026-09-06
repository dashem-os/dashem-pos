from dataclasses import dataclass
from enum import Enum

from collections.abc import Iterable

from app.modules.capabilities.registry import CAPABILITY_REGISTRY, IMPLEMENTED_CAPABILITIES, resolve_dependencies


class BusinessNiche(str, Enum):
    FOOD_SERVICE = "FOOD_SERVICE"
    RETAIL = "RETAIL"
    BEAUTY_RESELLER = "BEAUTY_RESELLER"


@dataclass(frozen=True)
class NicheContract:
    key: BusinessNiche
    name: str
    description: str
    required: tuple[str, ...]
    addons: tuple[str, ...]

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset((*self.required, *self.addons))


# Niches are commercial recommendation profiles. They seed a useful starting
# point, but never prevent a mixed business from contracting another capability.
NICHE_CONTRACTS: dict[BusinessNiche, NicheContract] = {
    BusinessNiche.FOOD_SERVICE: NicheContract(
        key=BusinessNiche.FOOD_SERVICE,
        name="Food Service",
        description="Atendimento de alimentação com delivery; mesas e produção são add-ons contratuais.",
        required=("catalog", "customer", "cash_management", "payments", "counter_order", "delivery_orders"),
        addons=("modifiers", "combos", "table_service", "kitchen_routing", "supervisor_override", "tef", "fiscal_nfce"),
    ),
    BusinessNiche.RETAIL: NicheContract(
        key=BusinessNiche.RETAIL,
        name="Retail",
        description="Varejo com estoque, checkout e canal de e-commerce, sem mesas ou KDS.",
        required=("catalog", "inventory", "customer", "cash_management", "payments", "barcode_scanning", "counter_order", "delivery_orders"),
        addons=("high_speed_checkout", "supervisor_override", "tef", "fiscal_nfce", "receivables"),
    ),
    BusinessNiche.BEAUTY_RESELLER: NicheContract(
        key=BusinessNiche.BEAUTY_RESELLER,
        name="Beauty Reseller",
        description="Revenda de beleza com catálogo e pedidos online, sem mesas ou KDS.",
        required=("catalog", "inventory", "customer", "cash_management", "payments", "delivery_orders"),
        addons=("barcode_scanning", "counter_order", "supervisor_override", "tef", "fiscal_nfce", "receivables"),
    ),
}


def entitlement_keys(niche: BusinessNiche, addon_keys: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    contract = NICHE_CONTRACTS[niche]
    requested = set(addon_keys)
    invalid = requested.difference(contract.addons)
    if invalid:
        raise ValueError(f"Add-ons não permitidos para {niche.value}: {', '.join(sorted(invalid))}")
    resolved = resolve_dependencies((*contract.required, *requested))
    outside_niche = set(resolved).difference(contract.allowed)
    if outside_niche:
        raise ValueError(f"Dependências fora do nicho {niche.value}: {', '.join(sorted(outside_niche))}")
    unavailable = set(resolved).difference(IMPLEMENTED_CAPABILITIES)
    if unavailable:
        raise ValueError(f"Capabilities ainda não executáveis: {', '.join(sorted(unavailable))}")
    return resolved


def selected_entitlement_keys(
    capability_keys: list[str] | tuple[str, ...],
    grandfathered: Iterable[str] = (),
) -> tuple[str, ...]:
    """As capabilities de um contrato, recusando o que não pode ser vendido.

    ``grandfathered`` são as que o tenant **já tem contratadas**. Elas passam
    mesmo incompletas, e a razão é simples: descobrir que uma capability é menos
    pronta do que se pensava não pode desligar quem já a usa nem impedir que o
    contrato dela seja mantido — trocar uma quota passaria a ser impossível. O
    que a prontidão governa é **contratar de novo**, não continuar existindo.
    """
    unknown = set(capability_keys).difference(CAPABILITY_REGISTRY)
    if unknown:
        raise ValueError(f"Capabilities desconhecidas: {', '.join(sorted(unknown))}")
    resolved = resolve_dependencies(capability_keys)
    unavailable = set(resolved).difference(IMPLEMENTED_CAPABILITIES).difference(set(grandfathered))
    if unavailable:
        raise ValueError(f"Capabilities ainda não executáveis: {', '.join(sorted(unavailable))}")
    return resolved


def capability_payload(key: str) -> dict[str, object]:
    capability = CAPABILITY_REGISTRY[key]
    return {
        "key": capability.key,
        "name": capability.name,
        "description": capability.description,
        "scope": capability.scope.value,
        "requires": list(capability.requires),
    }
