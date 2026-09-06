"""Commercial offer composition without tenant authorization side effects."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from app.modules.capabilities.eligibility import eligibility_map
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
    grandfathered: Sequence[str] = (),
) -> dict[str, object]:
    """Return a proposal only; callers must persist a contract to grant access.

    ``grandfathered`` são as capabilities que o tenant **já tem contratadas**.
    Elas atravessam a composição inteira: não são recusadas por prontidão, não
    entram em ``gaps`` e não somem da proposta quando a versão corrente do plano
    deixou de listá-las. O plano que as vendeu é história, e história de contrato
    não se reescreve — o que a prontidão governa é contratar de novo (ADR-031).
    """

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
    carried = set(grandfathered)
    expanded = set(resolve_dependencies(tuple(sorted(requested))))
    unavailable = expanded.difference(IMPLEMENTED_CAPABILITIES).difference(carried)
    if unavailable:
        raise CommercialOfferError(
            "Capabilities ainda não executáveis: " + ", ".join(sorted(unavailable))
        )

    plan_keys = set(plan_capability_keys)
    # Um direito já contratado continua coberto mesmo quando a versão corrente
    # do plano parou de oferecê-lo. Sem isto, publicar uma nova versão de plano
    # transformaria a próxima edição de contrato de quem tem o direito antigo
    # numa recusa — e trocar uma quota viraria impossível.
    covered = plan_keys | carried
    proposed = expanded & covered
    gaps = expanded - covered
    capabilities: list[dict[str, object]] = []
    for key in sorted(proposed):
        rule_items = rules_by_capability.get(key, [])
        sources = {"PLAN"} if key in plan_keys else {"GRANDFATHERED"}
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

    # A elegibilidade do catálogo inteiro nesta composição, resolvida aqui e não
    # refeita por quem consome. A tela do Control lia plano e atividades e
    # repetia a conta em TypeScript — é assim que duas verdades divergem. E ela
    # é sensível a dependências: uma capability que se apoia em algo incompleto
    # não é entregável, por mais pronto que esteja o código dela (ADR-031).
    offered_by_activities = required | optional
    resolved_eligibility = eligibility_map(
        sorted(CAPABILITY_REGISTRY),
        plan_capability_keys=plan_keys,
        activity_capability_keys=offered_by_activities,
    )

    return {
        "activity_keys": list(activities),
        "capabilities": capabilities,
        "capability_keys": sorted(proposed),
        "eligibility": [
            {
                "key": key,
                "reason": item.reason.value,
                "blocked_by": item.blocked_by,
            }
            for key, item in sorted(resolved_eligibility.items())
        ],
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
