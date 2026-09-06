"""ADR-031 — elegibilidade é contextual, e por isso é derivada, nunca declarada.

"Esta capability está disponível?" não tem resposta absoluta. Ela depende da
composição do momento: qual plano, quais atividades, e — para o que ainda está
sendo construído — se o módulo executável existe.

Declarar teria repetido o defeito que originou este ADR. Foi um humano marcando
`tef` como implementada, e um catálogo de planos que nunca a incluiu, que
produziram uma capability com navegação, permissões e código, invisível para
todo tenant. Derivada, a lacuna aparece sozinha no dia em que nasce.

A ordem das razões importa, e não é arbitrária: **o que está em desenvolvimento
não é a mesma coisa que o que está fora do plano.** A primeira é dívida nossa e
nenhuma mudança comercial a resolve; a segunda é decisão de catálogo, e se
resolve marcando uma caixa. Confundi-las manda o Owner editar um plano para
liberar algo que não funcionaria de qualquer jeito.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from app.modules.capabilities.readiness import CAPABILITY_READINESS, ImplementationState
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, resolve_dependencies


class EligibilityReason(str, Enum):
    REACHABLE = "REACHABLE"
    # Dívida nossa: o módulo executável não faz o trabalho inteiro do contrato.
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    # Decisão comercial: o plano contratado não a inclui.
    NOT_IN_PLAN = "NOT_IN_PLAN"
    # Decisão comercial: nenhuma atividade selecionada a oferta.
    NOT_OFFERED_BY_ACTIVITIES = "NOT_OFFERED_BY_ACTIVITIES"


@dataclass(frozen=True)
class CapabilityEligibility:
    key: str
    reason: EligibilityReason
    # Qual capability travou esta, quando não foi ela mesma. Uma que depende de
    # algo incompleto não é entregável, por mais pronta que esteja o próprio
    # código dela — e dizer só "em desenvolvimento" esconderia de quem lê qual
    # é a dívida de verdade.
    blocked_by: str | None = None

    @property
    def reachable(self) -> bool:
        return self.reason is EligibilityReason.REACHABLE


def _incomplete_dependency(key: str) -> str | None:
    """A primeira coisa incompleta em que esta capability se apoia.

    O grafo é fechado por `resolve_dependencies`, então a checagem é transitiva:
    uma capability três níveis acima de um módulo que não existe também não
    consegue funcionar.
    """
    if key not in CAPABILITY_REGISTRY:
        return None
    for dependency in resolve_dependencies([key]):
        if dependency == key:
            continue
        readiness = CAPABILITY_READINESS.get(dependency)
        if readiness is None or readiness.implementation is not ImplementationState.COMPLETE:
            return dependency
    return None


def eligibility(
    key: str, *, plan_capability_keys: Iterable[str], activity_capability_keys: Iterable[str],
) -> CapabilityEligibility:
    """Se esta capability consegue chegar a um tenant com esta composição."""
    readiness = CAPABILITY_READINESS.get(key)
    # Em desenvolvimento vence as demais razões porque é a mais forte: mudar o
    # plano não faz o que não existe passar a existir.
    if readiness is None or readiness.implementation is not ImplementationState.COMPLETE:
        return CapabilityEligibility(key, EligibilityReason.IN_DEVELOPMENT)
    blocker = _incomplete_dependency(key)
    if blocker is not None:
        return CapabilityEligibility(key, EligibilityReason.IN_DEVELOPMENT, blocked_by=blocker)
    if key not in set(plan_capability_keys):
        return CapabilityEligibility(key, EligibilityReason.NOT_IN_PLAN)
    if key not in set(activity_capability_keys):
        return CapabilityEligibility(key, EligibilityReason.NOT_OFFERED_BY_ACTIVITIES)
    return CapabilityEligibility(key, EligibilityReason.REACHABLE)


def eligibility_map(
    keys: Iterable[str], *, plan_capability_keys: Iterable[str],
    activity_capability_keys: Iterable[str],
) -> dict[str, CapabilityEligibility]:
    """A mesma resposta para um catálogo inteiro, numa composição só.

    Existe para que nenhum consumidor recalcule elegibilidade por conta própria:
    a tela do Control lia plano e atividades e refazia a conta em TypeScript, o
    que é como duas verdades começam a divergir.
    """
    plan = set(plan_capability_keys)
    activities = set(activity_capability_keys)
    return {
        key: eligibility(key, plan_capability_keys=plan, activity_capability_keys=activities)
        for key in keys
    }
