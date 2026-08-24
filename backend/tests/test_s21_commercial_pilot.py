import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.api.v1.endpoints.control import (
    PilotCreate, PilotIncidentInput, PilotObservationInput, PilotScopeInput,
    PilotTransition, ProfileApply, apply_capability_profile, create_commercial_pilot,
    link_pilot_incident, list_capability_profiles, record_pilot_observation,
    transition_commercial_pilot,
)
from app.api.v1.endpoints.identity import PlatformTenantCreate, provision_platform_tenant
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import (
    ControlStatusEnum, OperationalHardeningRun, PlatformIncident,
    PlatformMembership, PlatformRoleEnum,
)


def _owner(session: Session) -> tuple[AuthPrincipal, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"s21-{subject}@example.test", full_name="S21 Owner")
    session.add(user); session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject, provider_email=user.email, email_verified=True))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit(); session.refresh(user)
    return AuthPrincipal(subject=subject, email=user.email, session_id=str(uuid.uuid4()), assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email"), user


def _ready_pilot(session: Session):
    principal, owner = _owner(session)
    suffix = uuid.uuid4().hex[:8]
    provisioned = provision_platform_tenant(
        PlatformTenantCreate(name=f"S21 {suffix}", slug=f"s21-{suffix}", first_store_name="Principal", first_store_code="MAIN"),
        principal, session,
    )
    food = next(row["revision"] for row in list_capability_profiles(principal, session) if row["revision"].profile_key == "FOOD_SERVICE")
    apply_capability_profile(provisioned.tenant.id, food.id, ProfileApply(reason="Escopo food service do piloto comercial."), principal, session)
    hardening = OperationalHardeningRun(
        release_sha="d9a70ce", environment="pilot", status="PASSED", rpo_target_minutes=15,
        rto_target_minutes=60, initiated_by=owner.id,
    )
    session.add(hardening); session.commit(); session.refresh(hardening)
    payload = PilotCreate(
        tenant_id=provisioned.tenant.id, store_id=provisioned.first_store.id, hardening_run_id=hardening.id,
        scope=PilotScopeInput(
            expected_registers=2, expected_employees=8,
            operating_modes=["COUNTER", "TABLE", "KITCHEN"],
            payment_methods=["CASH", "PIX", "MANUAL_CARD"],
        ),
    )
    projection = create_commercial_pilot(payload, principal, session)
    return principal, owner, provisioned, projection["pilot"]


def test_s21_requires_field_evidence_and_never_completes_a_paper_pilot():
    with Session(engine) as session:
        principal, _owner_user, _provisioned, pilot = _ready_pilot(session)
        assert pilot.status == "READY_FOR_FIELD_VALIDATION"
        with pytest.raises(HTTPException) as no_field:
            record_pilot_observation(
                pilot.id,
                PilotObservationInput(task_type="SALE", source_ref="sale://before-field", metrics={"duration_ms": 100}),
                principal, session,
            )
        assert no_field.value.status_code == 409

        started = transition_commercial_pilot(pilot.id, PilotTransition(action="START_FIELD", reason="Operação presencial autorizada pelo estabelecimento."), principal, session)
        assert started["pilot"].status == "FIELD_VALIDATION"
        with pytest.raises(HTTPException) as missing:
            transition_commercial_pilot(pilot.id, PilotTransition(action="COMPLETE_FIELD", reason="Tentativa sem observações suficientes."), principal, session)
        assert missing.value.status_code == 409

        for task in ("SALE", "PRODUCTION", "PAYMENT", "TRANSFER", "RECOVERY"):
            record_pilot_observation(
                pilot.id,
                PilotObservationInput(task_type=task, source_ref=f"operation://{task.lower()}/{uuid.uuid4()}", metrics={"duration_ms": 150, "errors": 0}),
                principal, session,
            )
        completed = transition_commercial_pilot(pilot.id, PilotTransition(action="COMPLETE_FIELD", reason="Cobertura mínima observada e revisada."), principal, session)
        assert completed["pilot"].status == "COMPLETED"
        assert completed["missing_tasks"] == []
        assert completed["field_evidence"] is True


def test_s21_rejects_fake_external_readiness_and_critical_incident_blocks_expansion():
    with Session(engine) as session:
        principal, owner, provisioned, pilot = _ready_pilot(session)
        hardening_id = pilot.hardening_run_id
        with pytest.raises(HTTPException) as fake_tef:
            create_commercial_pilot(PilotCreate(
                tenant_id=provisioned.tenant.id, store_id=provisioned.first_store.id, hardening_run_id=hardening_id,
                scope=PilotScopeInput(expected_registers=1, expected_employees=5, operating_modes=["COUNTER", "TABLE", "KITCHEN"], payment_methods=["TEF"], tef_homologated=False),
            ), principal, session)
        assert fake_tef.value.status_code == 422

        transition_commercial_pilot(pilot.id, PilotTransition(action="START_FIELD", reason="Início acompanhado do piloto em campo."), principal, session)
        incident = PlatformIncident(
            tenant_id=provisioned.tenant.id, title="Duplicidade operacional detectada", severity="SEV1",
            component="orders", sanitized_summary="Operação interrompida para preservar consistência.", opened_by=owner.id,
        )
        session.add(incident); session.commit(); session.refresh(incident)
        linked = link_pilot_incident(pilot.id, PilotIncidentInput(incident_id=incident.id, decision_reason="SEV1 bloqueia expansão até correção e novo gate."), principal, session)
        assert linked["pilot_status"] == "BLOCKED"
        with pytest.raises(HTTPException) as still_open:
            transition_commercial_pilot(pilot.id, PilotTransition(action="RESUME_AFTER_INCIDENT", reason="Tentativa antes da resolução formal."), principal, session)
        assert still_open.value.status_code == 409
        incident.status = ControlStatusEnum.RESOLVED; session.add(incident); session.commit()
        resumed = transition_commercial_pilot(pilot.id, PilotTransition(action="RESUME_AFTER_INCIDENT", reason="Correção validada e incidente formalmente resolvido."), principal, session)
        assert resumed["pilot"].status == "FIELD_VALIDATION"


def test_s21_prevents_parallel_active_pilot_dossiers_for_the_same_store():
    with Session(engine) as session:
        principal, _owner, provisioned, pilot = _ready_pilot(session)
        with pytest.raises(HTTPException) as duplicate:
            create_commercial_pilot(PilotCreate(
                tenant_id=provisioned.tenant.id,
                store_id=provisioned.first_store.id,
                hardening_run_id=pilot.hardening_run_id,
                scope=PilotScopeInput(
                    expected_registers=1,
                    expected_employees=5,
                    operating_modes=["COUNTER", "TABLE", "KITCHEN"],
                    payment_methods=["CASH"],
                ),
            ), principal, session)
        assert duplicate.value.status_code == 409
