from typing import Any, Optional

from sqlmodel import Session, select

from app.models.platform import (
    CapabilityProfileRevision, EntitlementStatusEnum, StoreCapabilityOverride,
    TenantCapability, TenantProfileAssignment,
)
from app.modules.capabilities.registry import (
    CAPABILITY_REGISTRY, IMPLEMENTED_CAPABILITIES, resolve_dependencies,
)
from app.services.contract_entitlement_service import resolve_contract_entitlements


TABLE_SERVICE_ACTIVITY = "FOOD_SERVICE"


def tenant_activity_keys(session: Session, tenant_id) -> tuple[str, ...]:
    """As atividades que este tenant declarou, contratadas ou legadas.

    O contrato versionado é a fonte quando existe. Antes dele, a atividade vivia
    na atribuição de perfil de capability, e é de lá que o Owner console lê até
    hoje — então é de lá que se lê aqui também, em vez de tratar "sem contrato"
    como "sem regra".

    Um tenant que não declarou atividade nenhuma devolve tupla vazia, e quem
    consulta decide. Para a jornada de mesa, decidir é recusar.
    """
    snapshot = resolve_contract_entitlements(session, tenant_id)
    if snapshot is not None:
        return tuple(snapshot.activity_keys)
    revision = session.exec(
        select(CapabilityProfileRevision)
        .join(
            TenantProfileAssignment,
            TenantProfileAssignment.revision_id == CapabilityProfileRevision.id,
        )
        .where(
            TenantProfileAssignment.tenant_id == tenant_id,
            TenantProfileAssignment.status == "ACTIVE",
        )
    ).first()
    return (revision.profile_key,) if revision is not None else ()


def capability_allowed_by_activity(session: Session, tenant_id, capability_key: str) -> bool:
    """Return whether a contracted capability is coherent with tenant activities.

    Atender mesa é assunto de food service. Nem uma permissão, nem uma linha de
    capability esquecida, nem um sortimento publicado devem abrir essa jornada
    para um tenant de beleza ou de varejo.

    O tenant legado — sem contrato versionado — **não** é mais exceção. Ele era,
    e o efeito prático da exceção era que quem nunca contratou nada tinha mais
    acesso do que quem contratou errado. Agora ele responde pela atividade que
    declarou no perfil; não tendo declarado nenhuma, a jornada é recusada.
    """
    if capability_key != "table_service":
        return True
    return TABLE_SERVICE_ACTIVITY in tenant_activity_keys(session, tenant_id)


def effective_capabilities(session: Session, tenant_id, store_id: Optional[object] = None) -> dict[str, dict[str, Any]]:
    entitlements = session.exec(
        select(TenantCapability).where(
            TenantCapability.tenant_id == tenant_id,
            TenantCapability.enabled.is_(True),
            TenantCapability.status.in_({EntitlementStatusEnum.CONFIGURED, EntitlementStatusEnum.ACTIVE}),
        )
    ).all()
    persisted = {item.key: dict(item.configuration) for item in entitlements if item.key in CAPABILITY_REGISTRY}
    snapshot = resolve_contract_entitlements(session, tenant_id)
    if snapshot is not None:
        enabled = {
            key: persisted.get(key, {})
            for key in snapshot.capability_keys
            if key in CAPABILITY_REGISTRY
        }
        # Exceção de homologação (ADR-031): capability que **não pode ser
        # vendida** habilitada por fora do contrato, para ser exercitada. Sem
        # isto o caminho existia só no papel — a leitura efetiva vinha do
        # snapshot e a concessão não tinha efeito nenhum.
        #
        # Três limites que fazem dela exceção e não porta dos fundos: a própria
        # linha declara que é override, a capability precisa estar fora da lista
        # de vendáveis, e tudo de que ela depende já precisa estar valendo —
        # ninguém liga TEF numa conta onde pagamentos não vale.
        for key, configuration in persisted.items():
            if key in enabled or key in IMPLEMENTED_CAPABILITIES:
                continue
            if configuration.get("homologation_override") is not True:
                continue
            requires = CAPABILITY_REGISTRY[key].requires
            if any(dependency not in enabled for dependency in requires):
                continue
            enabled[key] = configuration
    else:
        # Pre-contract tenants remain readable from their persisted grants. This
        # is explicit legacy state, never an inference from the current plan.
        enabled = persisted
    enabled = {
        key: value
        for key, value in enabled.items()
        if capability_allowed_by_activity(session, tenant_id, key)
    }
    if store_id:
        overrides = session.exec(
            select(StoreCapabilityOverride).where(
                StoreCapabilityOverride.tenant_id == tenant_id,
                StoreCapabilityOverride.store_id == store_id,
            )
        ).all()
        for override in overrides:
            # A store override can narrow or configure a contracted entitlement;
            # it can never mint a tenant entitlement by itself.
            if override.key not in enabled:
                continue
            if override.enabled:
                enabled[override.key] = {**enabled.get(override.key, {}), **override.configuration}
            else:
                enabled.pop(override.key, None)
    resolved = tuple(enabled) if snapshot is not None else resolve_dependencies(enabled)
    return {
        key: {
            "key": key,
            "version": CAPABILITY_REGISTRY[key].version,
            "scope": CAPABILITY_REGISTRY[key].scope.value,
            "configuration": enabled.get(key, {}),
            "inherited": key not in enabled,
        }
        for key in resolved
    }
