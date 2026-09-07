"""A regra FOOD, nas superfícies em que ela precisa valer.

Atender mesa é assunto de food service. Isso não é uma checagem num endpoint: é
uma regra que precisa dar a mesma resposta em toda superfície que toca a jornada
— autorizar a rota, publicar sortimento, ler catálogo e abrir comanda. Uma
superfície que responde diferente das outras é por onde a regra vaza.

A matriz cobre o que o produto vende: **Beleza** e **Comércio** sozinhos, os dois
juntos sem food service, e as combinações que incluem food service. E cobre o
tenant legado, que era exceção e deixou de ser.

O caminho exercitado aqui é o **autenticado** — `authorize_tenant_context` com
principal, membership e permissões reais —, não o bypass de desenvolvimento.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from activity_fixtures import (
    BEAUTY_RESELLER, FOOD_SERVICE, RETAIL, declare_activity, declare_contract_activities,
)
from app.core.context import authorize_tenant_context
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import (
    AuthIdentity, Membership, MembershipStatusEnum, RoleEnum, Store, Tenant,
    TenantStatusEnum, User,
)
from app.models.platform import EntitlementStatusEnum, TenantCapability
from app.modules.capabilities.service import effective_capabilities


TABLE_PATH = "/api/v1/tables"


def _tenant_with_activities(session: Session, activities: tuple[str, ...], *, table_capability: bool = True):
    """Um tenant que declarou estas atividades, com as capabilities do catálogo."""
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(
        name=f"Food rule {suffix}", slug=f"food-rule-{suffix}",
        status=TenantStatusEnum.ACTIVE,
    )
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"MTZ-{suffix}")
    session.add(store)
    session.flush()

    subject = str(uuid.uuid4())
    user = User(email=f"gerente-{suffix}@example.test", full_name="Gerente")
    session.add(user)
    session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject))
    session.add(Membership(
        user_id=user.id, tenant_id=tenant.id, store_id=None,
        role=RoleEnum.ADMIN, status=MembershipStatusEnum.ACTIVE,
    ))

    keys = ["catalog", "payments", "counter_order"]
    if table_capability:
        keys.append("table_service")
    for key in keys:
        session.add(TenantCapability(
            tenant_id=tenant.id, key=key, enabled=True,
            status=EntitlementStatusEnum.ACTIVE,
        ))
    session.commit()

    # A última declaração vence, então a ordem aqui é a ordem do contrato.
    for activity in activities:
        declare_activity(session, tenant.id, activity)
    return tenant.id, store.id, subject


def _principal(subject: str) -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject, email=f"{subject}@example.test",
        session_id=str(uuid.uuid4()), assurance_level="aal1", claims={"sub": subject},
    )


def _table_journey_allowed(tenant_id, store_id, subject) -> bool:
    """A rota de mesas, pelo caminho autenticado inteiro."""
    with Session(engine) as session:
        set_platform_db_context(session)
        try:
            authorize_tenant_context(
                session, _principal(subject), tenant_id, store_id, "GET", TABLE_PATH,
            )
        except HTTPException as exc:
            assert exc.status_code == 403, exc.detail
            return False
    return True


@pytest.mark.parametrize(
    ("nome", "atividades", "esperado"),
    [
        ("beleza sozinha", (BEAUTY_RESELLER,), False),
        ("comércio sozinho", (RETAIL,), False),
        ("food service sozinho", (FOOD_SERVICE,), True),
        ("legado sem atividade declarada", (), False),
    ],
)
def test_the_table_journey_answers_the_activity_not_the_capability_row(nome, atividades, esperado):
    """A capability está contratada em todos eles; só a atividade muda.

    É esse o ponto da regra: uma linha de `table_service` esquecida no banco não
    abre mesa para uma revendedora de beleza nem para uma loja de varejo.
    """
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, subject = _tenant_with_activities(session, atividades)

    assert _table_journey_allowed(tenant_id, store_id, subject) is esperado, nome


@pytest.mark.parametrize(
    ("nome", "atividades", "esperado"),
    [
        ("beleza + comércio, sem food service", (BEAUTY_RESELLER, RETAIL), False),
        ("comércio + food service", (RETAIL, FOOD_SERVICE), True),
        ("beleza + food service", (BEAUTY_RESELLER, FOOD_SERVICE), True),
        ("as três juntas", (BEAUTY_RESELLER, RETAIL, FOOD_SERVICE), True),
    ],
)
def test_a_truly_mixed_tenant_answers_by_the_set_of_activities(nome, atividades, esperado):
    """Duas atividades **ao mesmo tempo**, e não uma substituindo a outra.

    A atribuição de perfil é única por tenant, então declarar varejo e depois
    food service por ali não cria um tenant misto: cria um tenant que mudou de
    ramo. Misto de verdade só existe no contrato, que carrega `activity_keys`
    como lista — e é isso que esta matriz exercita, pelo caminho autenticado.
    """
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, subject = _tenant_with_activities(session, ())
        declare_contract_activities(session, tenant_id, atividades)

    assert _table_journey_allowed(tenant_id, store_id, subject) is esperado, nome


def test_a_mixed_tenant_keeps_the_counter_journey_alongside_the_table_one():
    """Nenhuma atividade vence a outra: a composição é aditiva.

    Um tenant de varejo **e** food service atende mesa sem perder o balcão, e
    operar uma das duas não retira a outra — a escolha da aba é do cliente da
    API, e o escopo do seletor de mesa é fixo por definição.
    """
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, subject = _tenant_with_activities(session, ())
        declare_contract_activities(session, tenant_id, (RETAIL, FOOD_SERVICE))

    assert _table_journey_allowed(tenant_id, store_id, subject) is True

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, None)
        caps = effective_capabilities(session, tenant_id, store_id)
    assert "table_service" in caps
    assert "counter_order" in caps, "a jornada de balcão não é retirada pela de mesa"


def test_losing_food_service_blocks_reactivating_an_existing_table_assortment():
    """O caminho real da perda: o sortimento já existe, e alguém o reativa.

    Validar apenas o que chega no payload deixava esta porta aberta — nenhum
    escopo era reenviado, então nada era revalidado, e um sortimento de mesa
    voltava a publicar num tenant que perdeu a atividade.
    """
    from app.core.context import TenantContext
    from app.models.assortment import AssortmentStatusEnum
    from app.services import assortment_service

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, _subject = _tenant_with_activities(session, ())
        declare_contract_activities(session, tenant_id, (RETAIL, FOOD_SERVICE))

    def _context(session):
        caps = tuple(effective_capabilities(session, tenant_id, store_id))
        return TenantContext(
            tenant_id=tenant_id, store_id=store_id, user_id=uuid.uuid4(), capabilities=caps,
        )

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, None)
        context = _context(session)
        created = assortment_service.create_assortment(
            session, context,
            code=f"MESA-{uuid.uuid4().hex[:6]}", name="Cardápio da mesa",
            scopes=[{"store_id": str(store_id), "sales_context": "TABLE"}],
            actor_id=context.user_id,
        )
        assortment_id = uuid.UUID(str(created["id"]))
        version = created["version"]

    # O tenant deixa de ser food service — só varejo permanece.
    with Session(engine) as session:
        set_platform_db_context(session)
        declare_contract_activities(session, tenant_id, (RETAIL,))

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, None)
        context = _context(session)
        assert "table_service" not in context.capabilities

        # Desativar continua possível: a regra impede publicar, não impede
        # corrigir. Prender o lojista num sortimento que ele não pode manter nem
        # remover seria transformar a proteção em armadilha.
        deactivated = assortment_service.update_assortment(
            session, context, assortment_id,
            expected_version=version, status=AssortmentStatusEnum.INACTIVE,
            actor_id=context.user_id,
        )
        assert deactivated["status"] == AssortmentStatusEnum.INACTIVE.value

        # Reativar, não. E nenhum escopo é reenviado nesta chamada — que é
        # exatamente o furo que existia.
        with pytest.raises(HTTPException) as refused:
            assortment_service.update_assortment(
                session, context, assortment_id,
                expected_version=deactivated["version"],
                status=AssortmentStatusEnum.ACTIVE,
                actor_id=context.user_id,
            )
        assert refused.value.status_code == 403
        assert "FOOD_SERVICE" in refused.value.detail


def test_declaring_food_service_without_the_capability_is_still_refused():
    """São duas exigências, e uma não substitui a outra."""
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, subject = _tenant_with_activities(
            session, (FOOD_SERVICE,), table_capability=False,
        )

    assert _table_journey_allowed(tenant_id, store_id, subject) is False


@pytest.mark.parametrize("atividades", [(BEAUTY_RESELLER,), (RETAIL,), ()])
def test_publishing_a_table_assortment_needs_the_same_activity(atividades):
    """Publicar para uma jornada exige a jornada.

    O sortimento é onde um produto passa a existir para uma jornada de venda.
    Antes, a permissão de catálogo abria essa porta para qualquer contexto — um
    tenant de beleza podia publicar sortimento de **mesa**, que a leitura depois
    recusava, mas que já ficava gravado e visível na Gestão como configuração
    legítima.
    """
    from app.core.context import TenantContext
    from app.services import assortment_service

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, _subject = _tenant_with_activities(session, atividades)

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, None)
        caps = tuple(effective_capabilities(session, tenant_id, store_id))
        context = TenantContext(
            tenant_id=tenant_id, store_id=store_id, user_id=uuid.uuid4(),
            capabilities=caps,
        )
        with pytest.raises(HTTPException) as refused:
            assortment_service.create_assortment(
                session, context,
                code=f"MESA-{uuid.uuid4().hex[:6]}", name="Cardápio indevido",
                scopes=[{"store_id": str(store_id), "sales_context": "TABLE"}],
                actor_id=context.user_id,
            )
        assert refused.value.status_code == 403
        assert "FOOD_SERVICE" in refused.value.detail


def test_publishing_a_counter_assortment_is_never_blocked_by_the_food_rule():
    """A regra governa a mesa, e só ela — balcão de varejo segue publicando."""
    from app.core.context import TenantContext
    from app.services import assortment_service

    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id, _subject = _tenant_with_activities(session, (RETAIL,))

    with Session(engine) as session:
        set_tenant_db_context(session, tenant_id, store_id, None)
        caps = tuple(effective_capabilities(session, tenant_id, store_id))
        context = TenantContext(
            tenant_id=tenant_id, store_id=store_id, user_id=uuid.uuid4(),
            capabilities=caps,
        )
        published = assortment_service.create_assortment(
            session, context,
            code=f"BALCAO-{uuid.uuid4().hex[:6]}", name="Vitrine de balcão",
            scopes=[{"store_id": str(store_id), "sales_context": "COUNTER"}],
            actor_id=context.user_id,
        )
    assert published["code"].startswith("BALCAO-")
