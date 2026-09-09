from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.context import TenantContext, get_tenant_context
from app.core.database import get_session
from app.modules.capabilities.service import effective_capabilities, tenant_activity_keys
from app.models.platform import ModuleContribution, TenantProfileAssignment, CapabilityProfileRevision
from app.services.contract_entitlement_service import resolve_contract_entitlements
from app.services.starter_catalog_service import is_homologation_tenant


router = APIRouter()


def _labelled(contribution, activities: set[str]):
    """O rótulo do nicho vem da malha, não de uma lista dentro deste arquivo.

    Uma contribuição declara em `metadata_json.label_variants` quais palavras
    valem para quais atividades contratadas, em ordem de precedência: quem
    contrata comida lê "Cardápios", quem não contrata lê o rótulo base. A regra
    fica ao lado do resto da malha de capabilities, de modo que um Harness leia
    a mesma linha em vez de reimplementar a decisão.

    Devolve uma cópia destacada: o chamador continua recebendo a forma do
    modelo e a linha do banco não é tocada.
    """
    variants = (contribution.metadata_json or {}).get("label_variants") or []
    for variant in variants:
        exigida = variant.get("when_activity")
        rotulo = variant.get("label")
        if exigida and rotulo and exigida in activities:
            return contribution.model_copy(update={"label": rotulo})
    return contribution


@router.get("/effective")
def get_effective_capabilities(
    context: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_session),
):
    capabilities = effective_capabilities(session, context.tenant_id, context.store_id)
    enabled_keys = set(capabilities)
    contributions = session.exec(
        select(ModuleContribution).where(ModuleContribution.is_active.is_(True)).order_by(ModuleContribution.sort_order)
    ).all()
    visible = [
        contribution for contribution in contributions
        if (contribution.capability_key is None or contribution.capability_key in enabled_keys)
        and (contribution.permission_key is None or contribution.permission_key in context.permissions)
    ]
    assignment = session.exec(select(TenantProfileAssignment).where(
        TenantProfileAssignment.tenant_id == context.tenant_id,
        TenantProfileAssignment.status == "ACTIVE",
    )).first()
    revision = session.get(CapabilityProfileRevision, assignment.revision_id) if assignment else None
    contract_snapshot = resolve_contract_entitlements(session, context.tenant_id)
    # **A mesma fonte que o portão usa.** Antes, a resposta lia atividade só do
    # contrato versionado, enquanto `capability_allowed_by_activity` lia de
    # `tenant_activity_keys` — que cai no perfil declarado quando não há
    # contrato. Os dois discordavam, e o efeito era o pior possível: para um
    # tenant com perfil FOOD_SERVICE e sem contrato, o servidor **autorizava**
    # `table_service` e devolvia o card de Ambientes e mesas, e a tela o
    # escondia, porque `activities` vinha vazio. A jornada existia e não tinha
    # como ser alcançada.
    declaradas = list(tenant_activity_keys(session, context.tenant_id))
    activities = set(declaradas)
    return {
        "capabilities": capabilities,
        "permissions": list(context.permissions),
        "contributions": [_labelled(item, activities) for item in visible],
        "activities": declaradas,
        # Lets the console offer the starter catalogue only where it belongs.
        "homologation": is_homologation_tenant(session, context.tenant_id),
        "contract": (
            {
                "id": str(contract_snapshot.contract_id),
                "version": contract_snapshot.contract_version,
                "schema_version": contract_snapshot.schema_version,
            }
            if contract_snapshot else None
        ),
        "profile": (
            {"key": revision.profile_key, "version": revision.version}
            if revision and contract_snapshot is None else None
        ),
        "context": {
            "tenant_id": str(context.tenant_id),
            "store_id": str(context.store_id) if context.store_id else None,
            "membership_id": str(context.membership_id) if context.membership_id else None,
        },
    }
