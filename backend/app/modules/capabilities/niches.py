from dataclasses import dataclass
from enum import Enum

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


# The niche catalog is an executable commercial boundary. Anything outside the
# selected niche cannot become an entitlement, even when it exists in the
# global architecture catalog.
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


def capability_payload(key: str) -> dict[str, object]:
    capability = CAPABILITY_REGISTRY[key]
    return {
        "key": capability.key,
        "name": capability.name,
        "description": capability.description,
        "scope": capability.scope.value,
        "requires": list(capability.requires),
    }
