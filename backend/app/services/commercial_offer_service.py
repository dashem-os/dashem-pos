"""Commercial offer composition without tenant authorization side effects."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from app.modules.capabilities.registry import (
    CAPABILITY_REGISTRY,
    IMPLEMENTED_CAPABILITIES,
    resolve_dependencies,
)


class CommercialOfferError(ValueError):
    pass


@dataclass(frozen=True)
class ActivityRule:
    activity_key: str
    capability_key: str
    role: str
    default_selected: bool = False


def compose_commercial_offer(
    *,
    plan_capability_keys: Sequence[str],
    plan_activity_keys: Sequence[str],
    selected_activity_keys: Sequence[str],
    rules: Iterable[ActivityRule],
    requested_addon_keys: Sequence[str] = (),
) -> dict[str, object]:
    """Return a proposal only; callers must persist a contract to grant access."""

    activities = tuple(dict.fromkeys(selected_activity_keys))
    if not activities:
        raise CommercialOfferError("Selecione ao menos uma atividade comercial.")
    unsupported_activities = set(activities).difference(plan_activity_keys)
    if unsupported_activities:
        raise CommercialOfferError(
            "Atividades incompatíveis com o plano: "
            + ", ".join(sorted(unsupported_activities))
        )

    rules_by_capability: dict[str, list[ActivityRule]] = defaultdict(list)
    for rule in rules:
        if rule.activity_key in activities:
            rules_by_capability[rule.capability_key].append(rule)
    if not rules_by_capability:
        raise CommercialOfferError("As atividades selecionadas não possuem matriz comercial ativa.")

    required = {
        key for key, items in rules_by_capability.items()
        if any(item.role == "REQUIRED" for item in items)
    }
    optional = {
        key for key, items in rules_by_capability.items()
        if any(item.role == "OPTIONAL" for item in items)
    }
    requested_addons = set(requested_addon_keys)
    invalid_addons = requested_addons.difference(optional)
    if invalid_addons:
        raise CommercialOfferError(
            "Capabilities não são opcionais das atividades selecionadas: "
            + ", ".join(sorted(invalid_addons))
        )

    requested = required | requested_addons
    unknown = requested.difference(CAPABILITY_REGISTRY)
    if unknown:
        raise CommercialOfferError(
            "Capabilities desconhecidas na matriz: " + ", ".join(sorted(unknown))
        )
    expanded = set(resolve_dependencies(tuple(sorted(requested))))
    unavailable = expanded.difference(IMPLEMENTED_CAPABILITIES)
    if unavailable:
        raise CommercialOfferError(
            "Capabilities ainda não executáveis: " + ", ".join(sorted(unavailable))
        )

    plan_keys = set(plan_capability_keys)
    proposed = expanded & plan_keys
    gaps = expanded - plan_keys
    capabilities: list[dict[str, object]] = []
    for key in sorted(proposed):
        rule_items = rules_by_capability.get(key, [])
        sources = {"PLAN"}
        if key in required:
            sources.add("ACTIVITY")
        if key in requested_addons:
            sources.add("ADDON")
        if key not in requested:
            sources.add("DEPENDENCY")
        capabilities.append(
            {
                "key": key,
                "name": CAPABILITY_REGISTRY[key].name,
                "sources": sorted(sources),
                "activity_keys": sorted({item.activity_key for item in rule_items}),
            }
        )

    return {
        "activity_keys": list(activities),
        "capabilities": capabilities,
        "capability_keys": sorted(proposed),
        "gaps": [
            {
                "key": key,
                "name": CAPABILITY_REGISTRY[key].name,
                "reason": "REQUIRED_NOT_INCLUDED_IN_PLAN" if key in required else "DEPENDENCY_NOT_INCLUDED_IN_PLAN",
            }
            for key in sorted(gaps)
        ],
        "authorizes_tenant": False,
    }
