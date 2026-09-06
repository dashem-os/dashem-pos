import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.capabilities import get_effective_capabilities
from app.api.v1.endpoints.control import ProfileApply, apply_capability_profile, list_capability_profiles
from app.api.v1.endpoints.identity import (
    PlatformTenantCreate, TenantCapabilityUpdate, _homologation_override_keys,
    provision_platform_tenant, update_tenant_capability,
)
from app.core.context import TenantContext
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import (
    CapabilityProfileRevision, PlatformMembership, PlatformRoleEnum,
    StoreCapabilityOverride, TenantCapability, TenantProfileAssignment,
)
from app.modules.capabilities.service import effective_capabilities


def _owner(session: Session) -> tuple[AuthPrincipal, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"s19-{subject}@example.test", full_name="S19 Owner")
    session.add(user); session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject, provider_email=user.email, email_verified=True))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit(); session.refresh(user)
    return AuthPrincipal(subject=subject, email=user.email, session_id=str(uuid.uuid4()), assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email"), user


def test_s19_profiles_are_versioned_shortcuts_and_contributions_are_effective():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, owner = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(name=f"S19 {suffix}", slug=f"s19-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
            principal, session,
        )
        profiles = list_capability_profiles(principal, session)
        retail = next(row["revision"] for row in profiles if row["revision"].profile_key == "RETAIL")
        food = next(row["revision"] for row in profiles if row["revision"].profile_key == "FOOD_SERVICE")
        grocery = next(row["revision"] for row in profiles if row["revision"].profile_key == "GROCERY")

        result = apply_capability_profile(
            provisioned.tenant.id, retail.id, ProfileApply(reason="Contrato de varejo aprovado para validação."), principal, session,
        )
        assert result["profile"] == {"key": "RETAIL", "version": "2.0.0"}
        assert "catalog" in result["capabilities"] and "table_service" not in result["capabilities"]

        context = TenantContext(
            tenant_id=provisioned.tenant.id, store_id=provisioned.first_store.id,
            user_id=owner.id, permissions=("management.read", "catalog.read", "sale.read", "cash.read", "inventory.read", "customer.read", "receivable.read", "team.read", "device.read", "table.read"),
        )
        effective = get_effective_capabilities(context=context, session=session)
        navigation = {item.contribution_key for item in effective["contributions"] if item.surface == "MANAGEMENT_NAV"}
        assert {"overview", "sales", "cash", "products", "categories", "inventory", "customers", "team", "devices"} <= navigation
        assert "receivables" not in navigation  # commercial add-on, not RETAIL base
        assert "tables" not in navigation
        assert effective["profile"] == {"key": "RETAIL", "version": "2.0.0"}

        # Migrating profiles ends the old assignment but preserves entitlement rows.
        apply_capability_profile(
            provisioned.tenant.id, food.id, ProfileApply(reason="Migração contratual para operação food service."), principal, session,
        )
        assignments = list(session.exec(select(TenantProfileAssignment).where(TenantProfileAssignment.tenant_id == provisioned.tenant.id)).all())
        assert {item.status for item in assignments} == {"ACTIVE", "ENDED"}
        inventory = session.exec(select(TenantCapability).where(TenantCapability.tenant_id == provisioned.tenant.id, TenantCapability.key == "inventory")).one()
        assert inventory.enabled is False
        # Mesas e KDS are commercial add-ons in OWNER-P0, not implicit in the
        # Food Service base profile.
        assert "tables" not in {item.contribution_key for item in get_effective_capabilities(context=context, session=session)["contributions"]}

        with pytest.raises(HTTPException) as draft:
            apply_capability_profile(provisioned.tenant.id, grocery.id, ProfileApply(reason="Profile futuro não pode ser ativado."), principal, session)
        assert draft.value.status_code == 409


def test_s19_unimplemented_modules_and_store_minting_are_rejected():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, _ = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(name=f"S19 Guard {suffix}", slug=f"s19-guard-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
            principal, session,
        )
        with pytest.raises(HTTPException) as unavailable:
            update_tenant_capability(
                provisioned.tenant.id, "self_checkout",
                TenantCapabilityUpdate(enabled=True, reason="Tentativa de vender módulo sem implementação."),
                principal, session,
            )
        assert unavailable.value.status_code == 409

        session.add(StoreCapabilityOverride(
            tenant_id=provisioned.tenant.id, store_id=provisioned.first_store.id,
            key="inventory", enabled=True, configuration={"source": "invalid-store-mint"},
        ))
        session.commit()
        assert "inventory" not in effective_capabilities(session, provisioned.tenant.id, provisioned.first_store.id)


def test_incomplete_capability_is_reachable_only_through_a_declared_homologation_override():
    """ADR-031 — exercitar o que está sendo construído tem caminho, e ele é dito.

    Um gate que só sabe recusar cria o incentivo de mentir na declaração de
    prontidão para conseguir testar — foi assim que `tef` foi parar na lista de
    vendável. Então existe uma porta, e ela é explícita no ato: a fase de teste
    é o padrão de todo tenant novo, e sozinha abriria o gate para todos.
    """
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, _ = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(
                name=f"Homologação {suffix}", slug=f"homolog-{suffix}",
                first_store_name="Matriz", first_store_code="MAIN",
            ),
            principal, session,
        )
        # Sem declarar nada, a recusa continua de pé e diz o que falta.
        with pytest.raises(HTTPException) as refused:
            update_tenant_capability(
                provisioned.tenant.id, "tef",
                TenantCapabilityUpdate(enabled=True, reason="Tentativa sem declarar override."),
                principal, session,
            )
        assert refused.value.status_code == 409
        assert "transporte de comandos" in refused.value.detail

        # O que ela precisa por baixo precisa estar valendo antes: uma exceção
        # não concede `payments` de graça.
        update_tenant_capability(
            provisioned.tenant.id, "payments",
            TenantCapabilityUpdate(enabled=True, reason="Pagamentos para a base do TEF."),
            principal, session,
        )

        # Declarado, o tenant de homologação consegue exercitar o incompleto.
        catalog = update_tenant_capability(
            provisioned.tenant.id, "tef",
            TenantCapabilityUpdate(
                enabled=True, homologation_override=True,
                reason="Habilitado para exercitar o TEF no tenant de homologação.",
            ),
            principal, session,
        )
        assert next(item for item in catalog if item.key == "tef").enabled is True
        # E a prontidão do produto não muda por isso: continua incompleta.
        row = next(item for item in catalog if item.key == "tef")
        assert row.implementation == "PARTIAL"
        # A homologação viaja por integração, e não vira um estado solto.
        assert [entry["integration"] for entry in row.homologations] == ["SITEF"]


def test_the_homologation_exception_reaches_a_tenant_that_already_has_a_contract():
    """ADR-031 — o caminho precisa existir onde ele é necessário.

    Todo tenant de homologação tem contrato versionado, e a rota recusava
    qualquer alteração de capability nesse caso. O caminho existia só onde não
    fazia falta. A exceção passa, e passa **declarada**: a trilha grava que foi
    override, o que ainda falta e sobre qual versão do contrato ela correu, para
    que nenhuma leitura futura confunda "ligada" com "vendida".
    """
    import json

    from app.models.platform import TenantContract
    from app.models.reliability import AuditEvent

    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, actor = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(
                name=f"Homologação contratada {suffix}", slug=f"homolog-contract-{suffix}",
                first_store_name="Matriz", first_store_code="MAIN",
            ),
            principal, session,
        )
        tenant_id = provisioned.tenant.id
        session.add(TenantContract(
            tenant_id=tenant_id, version=1, status="ACTIVE", schema_version=4,
            capability_keys=["catalog", "payments"], activity_keys=["FOOD_SERVICE"],
            limits={}, limit_entitlements={}, created_by=actor.id,
            reason="Contrato de teste para a exceção de homologação.",
        ))
        session.commit()

        # Uma alteração comum continua sendo recusada: contrato versionado muda
        # pelo editor de contrato, e isso não afrouxa.
        with pytest.raises(HTTPException) as contracted:
            update_tenant_capability(
                tenant_id, "combos",
                TenantCapabilityUpdate(enabled=True, reason="Alteração fora do editor."),
                principal, session,
            )
        assert contracted.value.status_code == 409
        assert "contrato versionado" in contracted.value.detail

        # A exceção de homologação atravessa, porque é sobre o que não pode ser
        # vendido — logo não pertence ao contrato.
        catalog = update_tenant_capability(
            tenant_id, "tef",
            TenantCapabilityUpdate(
                enabled=True, homologation_override=True,
                reason="Exercitar o TEF no tenant de homologação.",
            ),
            principal, session,
        )
        row = next(item for item in catalog if item.key == "tef")
        # A exceção não vira contratação: `enabled` continua dizendo o que o
        # contrato diz, e a exceção tem campo próprio.
        assert row.enabled is False
        assert row.homologation_override is True

        # E ela tem efeito real: sem isso o caminho existiria só no papel.
        effective = effective_capabilities(session, tenant_id)
        assert "tef" in effective

        # E ela não serve de atalho para mexer em limites contratuais.
        with pytest.raises(HTTPException) as limits:
            update_tenant_capability(
                tenant_id, "tef",
                TenantCapabilityUpdate(
                    enabled=True, homologation_override=True,
                    contract_limits={"terminals": 99},
                    reason="Tentativa de alterar limite pela exceção.",
                ),
                principal, session,
            )
        assert limits.value.status_code == 409
        assert "limites contratuais" in limits.value.detail

        entry = session.exec(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == "platform.tenant.capability_homologation_override",
            )
            .order_by(AuditEvent.created_at.desc())
        ).first()
        assert entry is not None, "a exceção precisa estar dita na trilha"
        recorded = json.loads(entry.payload)
        assert recorded["homologation_override"] is True
        assert recorded["capability_key"] == "tef"
        assert recorded["implementation"] == "PARTIAL"
        assert "transporte de comandos" in recorded["implementation_missing"]
        assert recorded["contract_version"] == 1
        assert recorded["lifecycle_phase"] == "TEST"


def test_the_homologation_exception_never_mints_what_it_stands_on():
    """A exceção liga o incompleto, não o que ele precisa por baixo.

    `tef` depende de `payments`. Numa conta onde pagamentos não vale, ligar o
    TEF por exceção seria conceder pagamentos de graça — e uma porta que concede
    o que não foi contratado deixa de ser exceção e vira porta dos fundos.
    """
    from app.models.platform import TenantContract

    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, actor = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(
                name=f"Homologação sem pagamentos {suffix}", slug=f"homolog-nopay-{suffix}",
                first_store_name="Matriz", first_store_code="MAIN",
            ),
            principal, session,
        )
        tenant_id = provisioned.tenant.id
        session.add(TenantContract(
            tenant_id=tenant_id, version=1, status="ACTIVE", schema_version=4,
            capability_keys=["catalog"], activity_keys=["FOOD_SERVICE"],
            limits={}, limit_entitlements={}, created_by=actor.id,
            reason="Contrato sem pagamentos, para provar a guarda de dependência.",
        ))
        session.commit()

        with pytest.raises(HTTPException) as refused:
            update_tenant_capability(
                tenant_id, "tef",
                TenantCapabilityUpdate(
                    enabled=True, homologation_override=True,
                    reason="Exceção sobre um contrato que não cobre pagamentos.",
                ),
                principal, session,
            )
        assert refused.value.status_code == 409
        assert "payments" in refused.value.detail

        # E a recusa é no ato: nada foi gravado, e nem `payments` nem `tef`
        # passaram a valer pela porta de trás.
        effective = effective_capabilities(session, tenant_id)
        assert "tef" not in effective
        assert "payments" not in effective
        assert _homologation_override_keys(session, tenant_id) == []


def test_the_homologation_exception_can_be_revoked_on_a_contracted_tenant():
    """Conceder e revogar têm que passar pelo mesmo caminho.

    O guarda de contrato versionado recusava a saída, então dava para ligar o
    incompleto e nunca mais desligá-lo por esta rota — um ciclo pela metade é
    como uma exceção temporária vira permanente.
    """
    import json

    from app.models.platform import TenantContract
    from app.models.reliability import AuditEvent

    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, actor = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(
                name=f"Revogação {suffix}", slug=f"revoke-{suffix}",
                first_store_name="Matriz", first_store_code="MAIN",
            ),
            principal, session,
        )
        tenant_id = provisioned.tenant.id
        session.add(TenantContract(
            tenant_id=tenant_id, version=1, status="ACTIVE", schema_version=4,
            capability_keys=["catalog", "payments"], activity_keys=["FOOD_SERVICE"],
            limits={}, limit_entitlements={}, created_by=actor.id,
            reason="Contrato para o ciclo completo da exceção.",
        ))
        session.commit()

        update_tenant_capability(
            tenant_id, "tef",
            TenantCapabilityUpdate(
                enabled=True, homologation_override=True,
                reason="Exercitar o TEF em homologação.",
            ),
            principal, session,
        )
        assert "tef" in effective_capabilities(session, tenant_id)

        catalog = update_tenant_capability(
            tenant_id, "tef",
            TenantCapabilityUpdate(enabled=False, reason="Encerrada a janela de homologação."),
            principal, session,
        )
        assert next(item for item in catalog if item.key == "tef").homologation_override is False
        assert "tef" not in effective_capabilities(session, tenant_id)
        assert _homologation_override_keys(session, tenant_id) == []

        entry = session.exec(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == "platform.tenant.capability_homologation_override_revoked",
            ).order_by(AuditEvent.created_at.desc())
        ).first()
        assert entry is not None
        assert json.loads(entry.payload)["capability_key"] == "tef"

        # E o contrato continua intocado: a exceção nunca foi parte dele, então
        # nem entrar nem sair dela mexe no que foi contratado.
        assert "payments" in effective_capabilities(session, tenant_id)


def test_leaving_the_test_phase_ends_every_homologation_exception():
    """Uma exceção não sobrevive à promoção do tenant.

    Ela existe para exercitar o que ainda não pode ser vendido. Continuar
    valendo em piloto ou produção faria dela exatamente o contrário: software
    incompleto em operação real, sem nunca ter passado pelo gate.
    """
    import json

    from app.api.v1.endpoints.identity import (
        PlatformTenantProfileUpdate, update_platform_tenant_profile,
    )
    from app.models.identity import TenantPhaseEnum, TenantTypeEnum
    from app.models.platform import TenantContract
    from app.models.reliability import AuditEvent

    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, actor = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(
                name=f"Promoção {suffix}", slug=f"promote-{suffix}",
                first_store_name="Matriz", first_store_code="MAIN",
            ),
            principal, session,
        )
        tenant_id = provisioned.tenant.id
        session.add(TenantContract(
            tenant_id=tenant_id, version=1, status="ACTIVE", schema_version=4,
            capability_keys=["catalog", "payments"], activity_keys=["FOOD_SERVICE"],
            limits={}, limit_entitlements={}, created_by=actor.id,
            reason="Contrato do tenant que será promovido.",
        ))
        session.commit()

        update_tenant_capability(
            tenant_id, "tef",
            TenantCapabilityUpdate(
                enabled=True, homologation_override=True,
                reason="Exercitar o TEF antes da promoção.",
            ),
            principal, session,
        )
        assert "tef" in effective_capabilities(session, tenant_id)

        update_platform_tenant_profile(
            tenant_id,
            PlatformTenantProfileUpdate(
                name=f"Promocao {suffix}", tenant_type=TenantTypeEnum.CUSTOMER,
                lifecycle_phase=TenantPhaseEnum.PILOT,
                postal_code="01310100", street="Avenida Paulista", street_number="1000",
                district="Bela Vista", city="São Paulo", state="SP",
            ),
            principal, session,
        )

        # A exceção acabou junto com a fase que a autorizava.
        assert "tef" not in effective_capabilities(session, tenant_id)
        assert _homologation_override_keys(session, tenant_id) == []
        # E o contrato segue de pé: só a exceção caiu.
        assert "payments" in effective_capabilities(session, tenant_id)

        entry = session.exec(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == "platform.tenant.capability_homologation_override_revoked",
            ).order_by(AuditEvent.created_at.desc())
        ).first()
        assert entry is not None
        assert json.loads(entry.payload)["capability_keys"] == ["tef"]
