"""ADR-031 — prontidão governa contratar de novo, não continuar existindo.

Quando se reconheceu que a NFC-e emite por um gateway que fabrica a chave de
acesso, ela deixou de ser vendável. Isso não pode desligar quem já a contratou,
nem travar a manutenção do contrato dela — descobrir uma verdade sobre o produto
não desfaz um contrato assinado.

O que muda é a oferta corrente, e ela muda **por nova versão de plano**: a
migração `056` não é reescrita, e a `081` publica a versão sem NFC-e ao lado da
revisão antiga, que continua existindo para os contratos que a assinaram.
"""

import uuid

from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.identity import ServicePlan, ServicePlanRevision, Tenant, User
from app.models.platform import TenantContract
from app.modules.capabilities.niches import selected_entitlement_keys
from app.modules.capabilities.registry import IMPLEMENTED_CAPABILITIES
from app.modules.capabilities.service import effective_capabilities


SEEDED_WITH_NFCE = ("DASHEM_OMNICHANNEL", "DASHEM_PERFORMANCE")


def test_nfce_cannot_be_newly_contracted_while_it_emits_through_a_fake_gateway():
    """O gate é sobre vender: contratar do zero o que não emite é recusado."""
    assert "fiscal_nfce" not in IMPLEMENTED_CAPABILITIES
    try:
        selected_entitlement_keys(["catalog", "payments", "fiscal_nfce"])
    except ValueError as exc:
        assert "fiscal_nfce" in str(exc)
    else:  # pragma: no cover - a recusa é o comportamento
        raise AssertionError("Contratar NFC-e nova deveria ser recusado.")


def test_a_contract_that_already_carries_nfce_can_still_be_maintained():
    """Manter não é contratar. Trocar uma quota não pode virar impossível."""
    carried = selected_entitlement_keys(
        ["catalog", "payments", "fiscal_nfce"],
        grandfathered=("fiscal_nfce",),
    )
    assert "fiscal_nfce" in carried
    # E o que nunca foi contratado continua barrado, mesmo na mesma chamada.
    try:
        selected_entitlement_keys(
            ["catalog", "payments", "fiscal_nfce", "tef"],
            grandfathered=("fiscal_nfce",),
        )
    except ValueError as exc:
        assert "tef" in str(exc) and "fiscal_nfce" not in str(exc)
    else:  # pragma: no cover
        raise AssertionError("O TEF não estava contratado e deveria ser recusado.")


def test_an_old_plan_still_lets_a_tenant_contract_everything_else():
    """A revisão antiga não vira uma armadilha para quem está nela.

    Ela lista NFC-e, que hoje não é vendável. Isso não pode contaminar o resto:
    todas as demais capabilities daquele plano continuam contratáveis.
    """
    with Session(engine) as session:
        set_platform_db_context(session)
        revision = session.exec(
            select(ServicePlanRevision)
            .join(ServicePlan, ServicePlan.id == ServicePlanRevision.plan_id)
            .where(ServicePlan.code == "DASHEM_OMNICHANNEL", ServicePlanRevision.version == 1)
        ).first()
    assert revision is not None, "a revisão original do plano precisa continuar existindo"
    assert "fiscal_nfce" in revision.capability_keys

    others = [key for key in revision.capability_keys if key != "fiscal_nfce"]
    resolved = selected_entitlement_keys(others)
    assert set(others).issubset(set(resolved))


def test_the_current_offer_no_longer_lists_nfce_but_history_keeps_it():
    """A oferta muda por versão; o passado permanece como foi."""
    with Session(engine) as session:
        set_platform_db_context(session)
        for code in SEEDED_WITH_NFCE:
            plan = session.exec(select(ServicePlan).where(ServicePlan.code == code)).one()
            assert "fiscal_nfce" not in plan.capability_keys, "a oferta corrente não a lista"
            assert plan.version >= 2, "a mudança é por nova versão, não por edição"
            history = session.exec(select(ServicePlanRevision).where(
                ServicePlanRevision.plan_id == plan.id,
                ServicePlanRevision.version == 1,
            )).one()
            assert "fiscal_nfce" in history.capability_keys, "a revisão assinada não se reescreve"
            current = session.exec(select(ServicePlanRevision).where(
                ServicePlanRevision.plan_id == plan.id,
                ServicePlanRevision.version == plan.version,
            )).one()
            assert "fiscal_nfce" not in current.capability_keys


def test_a_tenant_who_already_contracted_nfce_keeps_using_it():
    """Um contrato assinado continua valendo depois da reclassificação."""
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name=f"NFC-e histórica {suffix}", slug=f"nfce-legacy-{suffix}")
        author = User(email=f"contrato-{suffix}@example.test", full_name="Autor do contrato")
        session.add(tenant)
        session.add(author)
        session.flush()
        session.add(TenantContract(
            tenant_id=tenant.id, version=1, status="ACTIVE", schema_version=4,
            capability_keys=["catalog", "payments", "fiscal_nfce"],
            activity_keys=["FOOD_SERVICE"], limits={}, limit_entitlements={},
            created_by=author.id,
            reason="Contrato anterior à reclassificação da NFC-e.",
        ))
        session.commit()

        effective = effective_capabilities(session, tenant.id)
        assert "fiscal_nfce" in effective, (
            "reclassificar prontidão não desliga quem já contratou"
        )
        assert "payments" in effective


def _load_migration_081():
    """A migração é carregada pelo arquivo: o teste exercita o SQL que roda."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "081_plan_revision_without_nfce.py"
    )
    spec = importlib.util.spec_from_file_location("migration_081", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_downgrade_only_reverts_what_the_migration_itself_changed():
    """Um plano que já tinha retirado a NFC-e não é tocado por nenhum sentido.

    A primeira versão do downgrade devolvia a capability a qualquer plano que
    não a tivesse e cujo histórico já a tivesse carregado. Isso reintroduziria a
    NFC-e num plano que a removeu de propósito, antes desta migração existir —
    um downgrade que faz mais do que o upgrade fez não é reversão, é edição.

    O SQL roda numa transação que o teste desfaz: nada aqui sobrevive ao teste.
    """
    from decimal import Decimal

    from sqlalchemy import text

    migration = _load_migration_081()
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        set_platform_db_context(session)

        def _plan(code: str, keys: list[str], version: int) -> ServicePlan:
            plan = ServicePlan(
                code=code, name=code.title(), is_active=True, version=version,
                capability_keys=keys, activity_keys=["FOOD_SERVICE"],
                store_limit=1, user_limit=1, terminal_limit=1, storage_limit_mib=1024,
                monthly_price=Decimal("100.00"),
            )
            session.add(plan)
            session.flush()
            return plan

        def _revision(plan: ServicePlan, version: int, keys: list[str], reason: str) -> None:
            session.add(ServicePlanRevision(
                plan_id=plan.id, version=version, code=plan.code, name=plan.name,
                is_active=True, store_limit=plan.store_limit, user_limit=plan.user_limit,
                terminal_limit=plan.terminal_limit, storage_limit_mib=plan.storage_limit_mib,
                capability_keys=keys, activity_keys=["FOOD_SERVICE"],
                monthly_price=plan.monthly_price, reason=reason,
            ))
            session.flush()

        # Alvo legítimo: ainda oferece NFC-e quando a migração roda.
        alvo = _plan(f"ALVO_{suffix.upper()}", ["catalog", "payments", "fiscal_nfce"], 1)
        _revision(alvo, 1, ["catalog", "payments", "fiscal_nfce"], "Oferta original.")

        # Já resolvido por conta própria, **antes** desta migração: a versão
        # corrente não tem NFC-e, e o histórico tem. É exatamente a forma que
        # confundia o downgrade antigo.
        proprio = _plan(f"PROPRIO_{suffix.upper()}", ["catalog", "payments"], 2)
        _revision(proprio, 1, ["catalog", "payments", "fiscal_nfce"], "Oferta original.")
        _revision(proprio, 2, ["catalog", "payments"], "Retirada comercial da NFC-e.")
        session.flush()

        for statement in migration.UPGRADE_STATEMENTS:
            session.exec(text(statement))
        session.flush()
        session.refresh(alvo)
        session.refresh(proprio)
        assert "fiscal_nfce" not in alvo.capability_keys and alvo.version == 2
        assert proprio.capability_keys == ["catalog", "payments"] and proprio.version == 2, (
            "a migração não tem trabalho a fazer num plano que já resolveu isso"
        )

        for statement in migration.DOWNGRADE_STATEMENTS:
            session.exec(text(statement))
        session.flush()
        session.refresh(alvo)
        session.refresh(proprio)
        # O alvo volta exatamente ao que era.
        assert "fiscal_nfce" in alvo.capability_keys and alvo.version == 1
        # E o outro continua como estava, nas duas pontas do ciclo.
        assert "fiscal_nfce" not in proprio.capability_keys, (
            "o downgrade não devolve a NFC-e a quem a removeu de propósito"
        )
        assert proprio.version == 2

        session.rollback()
