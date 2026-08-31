import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.control import (
    ContractCreate, IncidentCreate, IncidentUpdate, LeadCreate, LeadTransition,
    OnboardingUpdate, SupportGrantCreate, SupportGrantDecision,
    control_health_components, control_workspace, create_contract, create_incident,
    create_lead, decide_support, request_support, transition_lead,
    update_incident, update_onboarding,
)
from app.api.v1.endpoints.identity import PlatformTenantCreate, provision_platform_tenant
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import (
    ControlStatusEnum, LeadStatusEnum, PlatformMembership, PlatformRoleEnum,
    SupportGrantStatusEnum, TenantCapability,
)
from app.models.reliability import AuditEvent


def _owner(session: Session) -> tuple[AuthPrincipal, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"s18-{subject}@example.test", full_name="S18 Owner")
    session.add(user); session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject, provider_email=user.email, email_verified=True))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit(); session.refresh(user)
    return AuthPrincipal(subject=subject, email=user.email, session_id=str(uuid.uuid4()), assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email"), user


def test_s18_control_legacy_contract_writer_is_closed_and_support_remains_audited():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, owner = _owner(session)
        provisioned = provision_platform_tenant(
            PlatformTenantCreate(name=f"S18 {suffix}", slug=f"s18-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
            principal, session,
        )
        tenant_id = provisioned.tenant.id
        session.add(TenantCapability(tenant_id=tenant_id, key="catalog", enabled=True))
        session.commit()

        with pytest.raises(HTTPException) as legacy_writer:
            create_contract(
                tenant_id, ContractCreate(capability_keys=["catalog"], limits={"stores": 1}, reason="Contrato aprovado para o piloto."),
                principal, session,
            )
        assert legacy_writer.value.status_code == 409
        assert "snapshot auditado" in str(legacy_writer.value.detail)

        checkpoint = update_onboarding(
            tenant_id, "CONTRACT", OnboardingUpdate(status="COMPLETED", evidence={"contract_version": 1}), principal, session,
        )
        assert checkpoint.completed_by == owner.id

        support = request_support(
            tenant_id,
            SupportGrantCreate(scope=["health:read"], reason="Diagnosticar fila travada no piloto.", expires_at=datetime.utcnow() + timedelta(hours=2)),
            principal, session,
        )
        assert support.status == SupportGrantStatusEnum.PENDING
        support = decide_support(
            support.id, SupportGrantDecision(status=SupportGrantStatusEnum.APPROVED, reason="Cliente aprovou janela assistida."), principal, session,
        )
        assert support.approved_by == owner.id and support.approved_at is not None

        incident = create_incident(
            IncidentCreate(tenant_id=tenant_id, title="Fila transacional retida", severity="SEV2", component="outbox", sanitized_summary="Eventos aguardam nova tentativa sem perda confirmada."),
            principal, session,
        )
        incident = update_incident(
            incident.id, IncidentUpdate(status=ControlStatusEnum.RESOLVED, sanitized_summary="Fila drenada e causa corrigida."), principal, session,
        )
        assert incident.resolved_at is not None

        workspace = control_workspace(tenant_id, principal, session)
        assert workspace["contracts"] == []
        assert next(item for item in workspace["onboarding"] if (item.key if hasattr(item, "key") else item["key"]) == "CONTRACT")
        assert workspace["support_grants"][0].reason
        assert session.exec(select(AuditEvent).where(AuditEvent.action == "control.support.decided")).first() is not None


def test_s18_lead_conversion_and_unknown_health_are_explicit():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        principal, _ = _owner(session)
        lead = create_lead(LeadCreate(company_name="Lead real", contact_name="Contato", email="contato@example.test"), principal, session)
        with pytest.raises(HTTPException):
            transition_lead(lead.id, LeadTransition(status=LeadStatusEnum.CONVERTED, reason="Conversão sem tenant é inválida."), principal, session)
        tenant = provision_platform_tenant(
            PlatformTenantCreate(name=f"Converted {suffix}", slug=f"converted-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
            principal, session,
        ).tenant
        converted = transition_lead(lead.id, LeadTransition(status=LeadStatusEnum.CONVERTED, converted_tenant_id=tenant.id, reason="Contrato confirmado."), principal, session)
        assert converted.converted_tenant_id == tenant.id

        health = control_health_components(principal, session)
        assert {item["status"] for item in health["components"]} == {"UNINSTRUMENTED"}
        assert all(item["details"]["reason"] for item in health["components"])
