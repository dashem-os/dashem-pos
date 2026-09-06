"""Declarar a atividade comercial de um tenant de teste.

Atender mesa é assunto de food service, e a regra passou a valer também para o
tenant legado — o que não tem contrato versionado. Antes ele era exceção, e o
efeito prático da exceção era perverso: quem nunca declarou nada tinha mais
acesso do que quem declarou errado.

As fixtures que abrem mesa precisam, portanto, dizer o que o tenant é. Em
produção isso vem do contrato; num tenant legado vem da atribuição de perfil de
capability, que é a mesma fonte que o Owner console lê. É essa a declaração
mínima que estas funções escrevem.
"""

import uuid

from sqlmodel import Session, select

from app.core.tenancy import set_platform_db_context
from app.models.identity import User
from app.models.platform import CapabilityProfileRevision, TenantProfileAssignment


FOOD_SERVICE = "FOOD_SERVICE"
RETAIL = "RETAIL"
BEAUTY_RESELLER = "BEAUTY_RESELLER"
_AUTHOR_EMAIL = "fixture-atividade@example.test"


def declare_activity(session: Session, tenant_id, activity: str) -> None:
    """Atribuir ao tenant o perfil da atividade, como um tenant legado faria.

    A atribuição ativa é única por tenant (índice parcial), então declarar de
    novo substitui a anterior em vez de acumular — que é como o Owner console
    também se comporta ao trocar o perfil de um tenant.
    """
    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)
    revision = session.exec(
        select(CapabilityProfileRevision)
        .where(
            CapabilityProfileRevision.profile_key == activity,
            CapabilityProfileRevision.status == "ACTIVE",
        )
        .order_by(CapabilityProfileRevision.version.desc())
    ).first()
    assert revision is not None, f"Perfil de capability ausente para {activity}"

    for previous in session.exec(select(TenantProfileAssignment).where(
        TenantProfileAssignment.tenant_id == tenant_id,
        TenantProfileAssignment.status == "ACTIVE",
    )).all():
        previous.status = "SUPERSEDED"
        session.add(previous)
    session.flush()

    # A atribuição responde por um autor, como toda decisão de contrato neste
    # sistema. Na fixture ele é sintético, e existe só para a linha ser legítima.
    author = session.exec(select(User).where(User.email == _AUTHOR_EMAIL)).first()
    if author is None:
        author = User(email=_AUTHOR_EMAIL, full_name="Fixture de atividade")
        session.add(author)
        session.flush()

    session.add(TenantProfileAssignment(
        tenant_id=tenant_id, revision_id=revision.id, status="ACTIVE",
        reason=f"Atividade {activity} declarada pela fixture de teste.",
        assigned_by=author.id,
    ))
    session.commit()


def declare_food_service(session: Session, tenant_id) -> None:
    declare_activity(session, tenant_id, FOOD_SERVICE)


def declare_food_service_for(engine, tenant_id) -> None:
    """Versão de conveniência para fixtures que só têm o engine à mão."""
    with Session(engine) as session:
        set_platform_db_context(session)
        declare_food_service(session, tenant_id)


def declare_contract_activities(session: Session, tenant_id, activities: tuple[str, ...]) -> None:
    """Um tenant **misto**: várias atividades no mesmo contrato versionado.

    A atribuição de perfil de capability é única por tenant — índice parcial em
    `tenant_profile_assignments` — então declarar duas atividades por ali é
    impossível: a segunda substitui a primeira. Um tenant misto só existe pelo
    contrato, que carrega `activity_keys` como lista.

    É a diferença entre "o tenant mudou de ramo" e "o tenant tem dois ramos", e
    ela importa: só a segunda prova que mesa e balcão coexistem contratualmente.
    """
    from app.models.platform import TenantContract

    if isinstance(tenant_id, str):
        tenant_id = uuid.UUID(tenant_id)
    author = session.exec(select(User).where(User.email == _AUTHOR_EMAIL)).first()
    if author is None:
        author = User(email=_AUTHOR_EMAIL, full_name="Fixture de atividade")
        session.add(author)
        session.flush()

    latest = session.exec(
        select(TenantContract)
        .where(TenantContract.tenant_id == tenant_id)
        .order_by(TenantContract.version.desc())
    ).first()
    session.add(TenantContract(
        tenant_id=tenant_id, version=(latest.version + 1) if latest else 1,
        status="ACTIVE", schema_version=4,
        capability_keys=["catalog", "payments", "counter_order", "table_service"],
        activity_keys=list(activities), limits={}, limit_entitlements={},
        created_by=author.id,
        reason=f"Contrato de teste com atividades {', '.join(activities) or 'nenhuma'}.",
    ))
    session.commit()
