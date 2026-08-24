import json
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.access import require_platform_role
from app.core.database import get_session
from app.core.security import AuthPrincipal, get_current_principal
from app.models.identity import ServicePlan, Tenant, User
from app.models.platform import (
    AssistedSupportGrant, ControlStatusEnum, IdentityDeliveryEvent, Lead,
    LeadStatusEnum, PlatformIncident, PlatformRoleEnum, SupportGrantStatusEnum,
    TenantCapability, TenantContract, TenantOnboardingCheckpoint,
    CapabilityProfileRevision, CapabilityProfileRevisionItem, TenantProfileAssignment,
    OperationalHardeningRun, OperationalHardeningEvidence,
)
from app.models.reliability import AuditEvent, OutboxEvent, OutboxStatusEnum, ServiceHeartbeat
from app.services import reliability_service
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, IMPLEMENTED_CAPABILITIES, resolve_dependencies


router = APIRouter(dependencies=[Depends(get_current_principal)])
CONTROL_MANAGERS = {PlatformRoleEnum.PLATFORM_OWNER, PlatformRoleEnum.PLATFORM_ADMIN}
ONBOARDING_KEYS = (
    ("REGISTRATION", "Ficha cadastral validada"),
    ("CONTRACT", "Contrato e limites vigentes"),
    ("ADMIN_ACCESS", "Administrador contratual entregue"),
    ("CAPABILITIES", "Capacidades contratadas e configuradas"),
    ("STORE_SETUP", "Primeira unidade pronta"),
    ("GO_LIVE", "Gate de entrada em operação aprovado"),
)
HARDENING_CHECKS = {
    "isolation_matrix": "SECURITY",
    "concurrency_matrix": "CONSISTENCY",
    "retry_idempotency": "RELIABILITY",
    "degraded_dependencies": "RESILIENCE",
    "schema_migration": "DATA",
    "backup_restore": "DATA",
    "incident_response": "OPERATIONS",
    "representative_load": "PERFORMANCE",
    "auth_session": "SECURITY",
}


def _actor(session: Session, principal: AuthPrincipal) -> User:
    actor = require_platform_role(session, principal, CONTROL_MANAGERS, require_aal2=True)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authenticated platform user is required.")
    return actor


def _tenant(session: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    return tenant


def _audit(session: Session, actor: User, tenant_id: Optional[uuid.UUID], action: str, target: str, payload: dict[str, Any]) -> None:
    if tenant_id is None:
        session.add(AuditEvent(
            actor_id=actor.id, tenant_id=None, store_id=None, platform_scope=True,
            action=action, target=target, payload=json.dumps(payload, default=str),
        ))
        return
    audit, _ = reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action=action, target=target, audit_payload=payload, aggregate_type="control",
        aggregate_id=target, event_type=action, outbox_payload=payload,
    )
    audit.platform_scope = True
    session.add(audit)


class LeadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str = PydanticField(min_length=2, max_length=160)
    contact_name: str = PydanticField(min_length=2, max_length=160)
    email: Optional[str] = PydanticField(default=None, max_length=254)
    phone: Optional[str] = PydanticField(default=None, max_length=32)
    source: Optional[str] = PydanticField(default=None, max_length=80)
    notes: Optional[str] = PydanticField(default=None, max_length=2000)


class LeadTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: LeadStatusEnum
    reason: str = PydanticField(min_length=4, max_length=500)
    converted_tenant_id: Optional[uuid.UUID] = None


class ContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: Optional[uuid.UUID] = None
    status: str = PydanticField(default="ACTIVE", pattern=r"^(DRAFT|ACTIVE|PAUSED|ENDED)$")
    limits: dict[str, Any] = PydanticField(default_factory=dict)
    capability_keys: list[str] = PydanticField(default_factory=list)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    reason: str = PydanticField(min_length=4, max_length=1000)


class OnboardingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = PydanticField(pattern=r"^(PENDING|IN_PROGRESS|COMPLETED|BLOCKED)$")
    evidence: dict[str, Any] = PydanticField(default_factory=dict)


class SupportGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: list[str] = PydanticField(min_length=1, max_length=20)
    reason: str = PydanticField(min_length=8, max_length=1000)
    expires_at: datetime


class SupportGrantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: SupportGrantStatusEnum
    reason: str = PydanticField(min_length=4, max_length=500)


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = PydanticField(min_length=4, max_length=180)
    severity: str = PydanticField(pattern=r"^(SEV1|SEV2|SEV3|SEV4)$")
    component: str = PydanticField(min_length=2, max_length=80)
    sanitized_summary: str = PydanticField(min_length=8, max_length=2000)
    tenant_id: Optional[uuid.UUID] = None
    correlation_id: Optional[str] = PydanticField(default=None, max_length=120)


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ControlStatusEnum
    sanitized_summary: str = PydanticField(min_length=8, max_length=2000)


class ProfileApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = PydanticField(min_length=8, max_length=1000)


class HardeningRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_sha: str = PydanticField(min_length=7, max_length=64, pattern=r"^[0-9a-fA-F]+$")
    environment: str = PydanticField(min_length=2, max_length=40)
    rpo_target_minutes: int = PydanticField(default=15, ge=0, le=1440)
    rto_target_minutes: int = PydanticField(default=60, ge=1, le=10080)


class HardeningEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = PydanticField(pattern=r"^(PASS|FAIL|BLOCKED)$")
    evidence_ref: str = PydanticField(min_length=8, max_length=500)
    observed: dict[str, Any] = PydanticField(min_length=1)


def _hardening_projection(session: Session, run: OperationalHardeningRun) -> dict[str, Any]:
    rows = list(session.exec(select(OperationalHardeningEvidence).where(
        OperationalHardeningEvidence.run_id == run.id
    ).order_by(OperationalHardeningEvidence.check_key)).all())
    present = {row.check_key for row in rows}
    return {
        "run": run,
        "evidence": rows,
        "required_checks": HARDENING_CHECKS,
        "missing_checks": sorted(set(HARDENING_CHECKS) - present),
    }


def _validate_pass_evidence(run: OperationalHardeningRun, key: str, observed: dict[str, Any]) -> None:
    valid = {
        "isolation_matrix": int(observed.get("denied_cross_tenant", 0)) >= 1,
        "concurrency_matrix": observed.get("lost_operations") == 0 and observed.get("duplicate_operations") == 0,
        "retry_idempotency": observed.get("lost_operations") == 0 and observed.get("duplicate_operations") == 0,
        "degraded_dependencies": observed.get("capability_isolated") is True and observed.get("core_available") is True,
        "schema_migration": all(observed.get(item) is True for item in ("empty_db", "migrated_db", "no_drift")),
        "backup_restore": (
            observed.get("restore_verified") is True
            and float(observed.get("measured_rpo_minutes", run.rpo_target_minutes + 1)) <= run.rpo_target_minutes
            and float(observed.get("measured_rto_minutes", run.rto_target_minutes + 1)) <= run.rto_target_minutes
        ),
        "incident_response": all(observed.get(item) is True for item in ("detected", "diagnosed", "recovered")),
        "representative_load": int(observed.get("samples", 0)) > 0 and float(observed.get("error_rate", 1)) < 0.01,
        "auth_session": observed.get("aal2_enforced") is True and observed.get("pin_lockout") is True,
    }[key]
    if not valid:
        raise HTTPException(status_code=422, detail=f"Evidência PASS inválida para {key}.")


def _recompute_hardening_status(session: Session, run: OperationalHardeningRun) -> None:
    rows = list(session.exec(select(OperationalHardeningEvidence).where(
        OperationalHardeningEvidence.run_id == run.id
    )).all())
    by_key = {row.check_key: row for row in rows}
    if set(by_key) == set(HARDENING_CHECKS) and all(row.status == "PASS" for row in rows):
        run.status = "PASSED"
        run.completed_at = datetime.utcnow()
    elif any(row.status in {"FAIL", "BLOCKED"} for row in rows):
        run.status = "BLOCKED"
        run.completed_at = None
    else:
        run.status = "IN_PROGRESS"
        run.completed_at = None
    run.updated_at = datetime.utcnow()
    session.add(run)


@router.get("/leads", response_model=list[Lead])
def list_leads(principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    _actor(session, principal)
    return list(session.exec(select(Lead).order_by(Lead.created_at.desc())).all())


@router.post("/leads", response_model=Lead, status_code=201)
def create_lead(data: LeadCreate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    lead = Lead(**data.model_dump(), owner_user_id=actor.id)
    session.add(lead); session.flush()
    _audit(session, actor, None, "control.lead.created", f"lead:{lead.id}", {"lead_id": str(lead.id), "source": lead.source})
    session.commit(); session.refresh(lead)
    return lead


@router.patch("/leads/{lead_id}", response_model=Lead)
def transition_lead(lead_id: uuid.UUID, data: LeadTransition, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead não encontrado.")
    if data.status == LeadStatusEnum.CONVERTED:
        if data.converted_tenant_id is None:
            raise HTTPException(status_code=422, detail="Conversão exige o tenant provisionado.")
        _tenant(session, data.converted_tenant_id)
        lead.converted_tenant_id = data.converted_tenant_id
        lead.converted_at = datetime.utcnow()
    elif data.converted_tenant_id is not None:
        raise HTTPException(status_code=422, detail="Tenant convertido só é aceito no estado CONVERTED.")
    previous = getattr(lead.status, "value", str(lead.status))
    lead.status = data.status; lead.updated_at = datetime.utcnow(); session.add(lead)
    _audit(session, actor, data.converted_tenant_id, "control.lead.transitioned", f"lead:{lead.id}", {"from": previous, "to": data.status.value, "reason": data.reason})
    session.commit(); session.refresh(lead)
    return lead


@router.get("/tenants/{tenant_id}/workspace")
def control_workspace(tenant_id: uuid.UUID, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    _actor(session, principal); _tenant(session, tenant_id)
    checkpoints = {item.key: item for item in session.exec(select(TenantOnboardingCheckpoint).where(TenantOnboardingCheckpoint.tenant_id == tenant_id)).all()}
    contracts = list(session.exec(select(TenantContract).where(TenantContract.tenant_id == tenant_id).order_by(TenantContract.version.desc())).all())
    deliveries = list(session.exec(select(IdentityDeliveryEvent).where(IdentityDeliveryEvent.tenant_id == tenant_id).order_by(IdentityDeliveryEvent.occurred_at.desc()).limit(50)).all())
    grants = list(session.exec(select(AssistedSupportGrant).where(AssistedSupportGrant.tenant_id == tenant_id).order_by(AssistedSupportGrant.created_at.desc())).all())
    incidents = list(session.exec(select(PlatformIncident).where(PlatformIncident.tenant_id == tenant_id).order_by(PlatformIncident.opened_at.desc())).all())
    pending = int(session.exec(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.tenant_id == tenant_id, OutboxEvent.status.in_({OutboxStatusEnum.PENDING, OutboxStatusEnum.PROCESSING}))).one() or 0)
    failed_rows = list(session.exec(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant_id, OutboxEvent.status == OutboxStatusEnum.FAILED).order_by(OutboxEvent.created_at.desc()).limit(5)).all())
    last_audit = session.exec(select(func.max(AuditEvent.created_at)).where(AuditEvent.tenant_id == tenant_id)).one()
    return {
        "tenant_id": tenant_id, "contracts": contracts,
        "onboarding": [checkpoints.get(key) or {"key": key, "label": label, "status": "PENDING", "evidence": {}} for key, label in ONBOARDING_KEYS],
        "identity_timeline": deliveries, "support_grants": grants, "incidents": incidents,
        "operations": {"backlog": pending, "failed": len(failed_rows), "last_sync_at": last_audit, "last_errors": [{"event_type": row.event_type, "occurred_at": row.occurred_at, "detail": (row.last_error or "Falha sem detalhe instrumentado")[:180]} for row in failed_rows]},
    }


@router.post("/tenants/{tenant_id}/contracts", response_model=TenantContract, status_code=201)
def create_contract(tenant_id: uuid.UUID, data: ContractCreate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal); _tenant(session, tenant_id)
    if data.plan_id and session.get(ServicePlan, data.plan_id) is None:
        raise HTTPException(status_code=422, detail="Plano não encontrado.")
    contracted = {row.key for row in session.exec(select(TenantCapability).where(TenantCapability.tenant_id == tenant_id, TenantCapability.enabled.is_(True))).all()}
    if not set(data.capability_keys).issubset(contracted):
        raise HTTPException(status_code=409, detail="Contrato não pode incluir capability sem entitlement ativo.")
    latest = session.exec(select(func.max(TenantContract.version)).where(TenantContract.tenant_id == tenant_id)).one() or 0
    contract = TenantContract(tenant_id=tenant_id, version=int(latest) + 1, created_by=actor.id, **data.model_dump())
    session.add(contract); session.flush()
    _audit(session, actor, tenant_id, "control.contract.versioned", f"contract:{contract.id}", {"version": contract.version, "reason": contract.reason})
    session.commit(); session.refresh(contract)
    return contract


@router.put("/tenants/{tenant_id}/onboarding/{key}", response_model=TenantOnboardingCheckpoint)
def update_onboarding(tenant_id: uuid.UUID, key: str, data: OnboardingUpdate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal); _tenant(session, tenant_id)
    labels = dict(ONBOARDING_KEYS)
    if key not in labels:
        raise HTTPException(status_code=404, detail="Checkpoint de onboarding desconhecido.")
    item = session.exec(select(TenantOnboardingCheckpoint).where(TenantOnboardingCheckpoint.tenant_id == tenant_id, TenantOnboardingCheckpoint.key == key)).first() or TenantOnboardingCheckpoint(tenant_id=tenant_id, key=key, label=labels[key])
    item.status = data.status; item.evidence = data.evidence; item.updated_at = datetime.utcnow()
    item.completed_by = actor.id if data.status == "COMPLETED" else None
    item.completed_at = datetime.utcnow() if data.status == "COMPLETED" else None
    session.add(item); session.flush()
    _audit(session, actor, tenant_id, "control.onboarding.updated", f"onboarding:{tenant_id}:{key}", {"status": data.status, "evidence_keys": sorted(data.evidence)})
    session.commit(); session.refresh(item)
    return item


@router.post("/tenants/{tenant_id}/support", response_model=AssistedSupportGrant, status_code=201)
def request_support(tenant_id: uuid.UUID, data: SupportGrantCreate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal); _tenant(session, tenant_id)
    if data.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=422, detail="O prazo do suporte deve estar no futuro.")
    grant = AssistedSupportGrant(tenant_id=tenant_id, requested_by=actor.id, scope=sorted(set(data.scope)), reason=data.reason.strip(), expires_at=data.expires_at)
    session.add(grant); session.flush()
    _audit(session, actor, tenant_id, "control.support.requested", f"support:{grant.id}", {"scope": grant.scope, "expires_at": grant.expires_at.isoformat(), "reason": grant.reason})
    session.commit(); session.refresh(grant)
    return grant


@router.patch("/support/{grant_id}", response_model=AssistedSupportGrant)
def decide_support(grant_id: uuid.UUID, data: SupportGrantDecision, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    grant = session.get(AssistedSupportGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="Autorização de suporte não encontrada.")
    if data.status not in {SupportGrantStatusEnum.APPROVED, SupportGrantStatusEnum.REVOKED}:
        raise HTTPException(status_code=422, detail="Decisão deve aprovar ou revogar o suporte.")
    grant.status = data.status; grant.approved_by = actor.id
    if data.status == SupportGrantStatusEnum.APPROVED:
        grant.approved_at = datetime.utcnow()
    else:
        grant.revoked_at = datetime.utcnow()
    session.add(grant)
    _audit(session, actor, grant.tenant_id, "control.support.decided", f"support:{grant.id}", {"status": data.status.value, "reason": data.reason})
    session.commit(); session.refresh(grant)
    return grant


@router.post("/incidents", response_model=PlatformIncident, status_code=201)
def create_incident(data: IncidentCreate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    if data.tenant_id: _tenant(session, data.tenant_id)
    incident = PlatformIncident(**data.model_dump(), opened_by=actor.id)
    session.add(incident); session.flush()
    _audit(session, actor, data.tenant_id, "control.incident.opened", f"incident:{incident.id}", {"severity": data.severity, "component": data.component})
    session.commit(); session.refresh(incident)
    return incident


@router.patch("/incidents/{incident_id}", response_model=PlatformIncident)
def update_incident(incident_id: uuid.UUID, data: IncidentUpdate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    incident = session.get(PlatformIncident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incidente não encontrado.")
    incident.status = data.status; incident.sanitized_summary = data.sanitized_summary; incident.updated_at = datetime.utcnow()
    if data.status == ControlStatusEnum.RESOLVED:
        incident.resolved_by = actor.id; incident.resolved_at = datetime.utcnow()
    session.add(incident)
    _audit(session, actor, incident.tenant_id, "control.incident.updated", f"incident:{incident.id}", {"status": data.status.value})
    session.commit(); session.refresh(incident)
    return incident


@router.get("/health/components")
def control_health_components(principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    _actor(session, principal)
    now = datetime.utcnow()
    required = {
        "outbox_worker": "Outbox worker", "fiscal_gateway": "Fiscal gateway",
        "tef_bridge": "TEF bridge", "channel_hub": "Channel Hub",
        "production_worker": "Production worker", "email_delivery": "E-mail transacional",
    }
    heartbeats = {row.service_key: row for row in session.exec(select(ServiceHeartbeat).where(ServiceHeartbeat.service_key.in_(set(required)))).all()}
    result = []
    for key, label in required.items():
        heartbeat = heartbeats.get(key)
        age = (now - heartbeat.last_seen_at).total_seconds() if heartbeat else None
        status = "UNINSTRUMENTED" if heartbeat is None else "DEGRADED" if age is not None and age > 90 else heartbeat.status
        result.append({"key": key, "label": label, "status": status, "last_seen_at": heartbeat.last_seen_at if heartbeat else None, "age_seconds": round(age, 1) if age is not None else None, "details": heartbeat.details if heartbeat else {"reason": "Nenhum heartbeat registrado."}})
    return {"checked_at": now, "components": result}


@router.get("/profiles")
def list_capability_profiles(principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    _actor(session, principal)
    revisions = list(session.exec(select(CapabilityProfileRevision).order_by(CapabilityProfileRevision.profile_key, CapabilityProfileRevision.version.desc())).all())
    items = list(session.exec(select(CapabilityProfileRevisionItem)).all())
    by_revision: dict[uuid.UUID, list[CapabilityProfileRevisionItem]] = {}
    for item in items: by_revision.setdefault(item.revision_id, []).append(item)
    return [{"revision": revision, "items": by_revision.get(revision.id, [])} for revision in revisions]


@router.post("/tenants/{tenant_id}/profiles/{revision_id}/apply")
def apply_capability_profile(tenant_id: uuid.UUID, revision_id: uuid.UUID, data: ProfileApply, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal); _tenant(session, tenant_id)
    revision = session.get(CapabilityProfileRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="Revisão de profile não encontrada.")
    if revision.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Somente profiles ativos podem ser aplicados.")
    items = list(session.exec(select(CapabilityProfileRevisionItem).where(CapabilityProfileRevisionItem.revision_id == revision_id)).all())
    requested = {item.capability_key for item in items}
    resolved = set(resolve_dependencies(requested))
    not_implemented = sorted(resolved - IMPLEMENTED_CAPABILITIES)
    if not_implemented:
        raise HTTPException(status_code=409, detail={"code": "MODULE_NOT_IMPLEMENTED", "capabilities": not_implemented})
    current = session.exec(select(TenantProfileAssignment).where(TenantProfileAssignment.tenant_id == tenant_id, TenantProfileAssignment.status == "ACTIVE")).first()
    if current and current.revision_id == revision_id:
        raise HTTPException(status_code=409, detail="Este profile já está ativo no tenant.")
    if current:
        current.status = "ENDED"; current.ended_at = datetime.utcnow(); session.add(current)
    existing = {row.key: row for row in session.exec(select(TenantCapability).where(TenantCapability.tenant_id == tenant_id)).all()}
    for key in resolved:
        row = existing.get(key) or TenantCapability(tenant_id=tenant_id, key=key)
        row.enabled = True; row.status = "ACTIVE"; row.updated_at = datetime.utcnow()
        profile_item = next((item for item in items if item.capability_key == key), None)
        if profile_item: row.configuration = dict(profile_item.default_configuration)
        session.add(row)
    # Preserve rows and history while removing inactive module availability.
    for key, row in existing.items():
        if key not in resolved:
            row.enabled = False; row.updated_at = datetime.utcnow(); session.add(row)
    assignment = TenantProfileAssignment(tenant_id=tenant_id, revision_id=revision_id, assigned_by=actor.id, reason=data.reason.strip())
    session.add(assignment); session.flush()
    _audit(session, actor, tenant_id, "control.profile.applied", f"profile_assignment:{assignment.id}", {"profile": revision.profile_key, "version": revision.version, "enabled": sorted(resolved), "reason": assignment.reason})
    session.commit(); session.refresh(assignment)
    return {"assignment": assignment, "profile": {"key": revision.profile_key, "version": revision.version}, "capabilities": sorted(resolved)}


@router.post("/hardening/runs", status_code=201)
def create_hardening_run(data: HardeningRunCreate, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    run = OperationalHardeningRun(initiated_by=actor.id, **data.model_dump())
    session.add(run); session.flush()
    _audit(session, actor, None, "control.hardening.started", f"hardening:{run.id}", {
        "release_sha": run.release_sha, "environment": run.environment,
        "rpo_target_minutes": run.rpo_target_minutes, "rto_target_minutes": run.rto_target_minutes,
    })
    session.commit(); session.refresh(run)
    return _hardening_projection(session, run)


@router.get("/hardening/runs/{run_id}")
def get_hardening_run(run_id: uuid.UUID, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    _actor(session, principal)
    run = session.get(OperationalHardeningRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execução de hardening não encontrada.")
    return _hardening_projection(session, run)


@router.put("/hardening/runs/{run_id}/evidence/{check_key}")
def record_hardening_evidence(run_id: uuid.UUID, check_key: str, data: HardeningEvidenceInput, principal: AuthPrincipal = Depends(get_current_principal), session: Session = Depends(get_session)):
    actor = _actor(session, principal)
    run = session.get(OperationalHardeningRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execução de hardening não encontrada.")
    if check_key not in HARDENING_CHECKS:
        raise HTTPException(status_code=404, detail="Verificação de hardening desconhecida.")
    if data.status == "PASS":
        _validate_pass_evidence(run, check_key, data.observed)
    evidence = session.exec(select(OperationalHardeningEvidence).where(
        OperationalHardeningEvidence.run_id == run_id,
        OperationalHardeningEvidence.check_key == check_key,
    )).first() or OperationalHardeningEvidence(
        run_id=run_id, check_key=check_key, category=HARDENING_CHECKS[check_key], recorded_by=actor.id,
        status=data.status, evidence_ref=data.evidence_ref, observed=data.observed,
    )
    evidence.status = data.status
    evidence.evidence_ref = data.evidence_ref
    evidence.observed = data.observed
    evidence.recorded_by = actor.id
    evidence.measured_at = datetime.utcnow()
    session.add(evidence); session.flush()
    _recompute_hardening_status(session, run)
    _audit(session, actor, None, "control.hardening.evidence.recorded", f"hardening:{run.id}:{check_key}", {
        "check_key": check_key, "status": data.status, "evidence_ref": data.evidence_ref,
        "observed_keys": sorted(data.observed),
    })
    session.commit(); session.refresh(run)
    return _hardening_projection(session, run)
