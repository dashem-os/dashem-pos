import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.v1.endpoints.control import (
    HARDENING_CHECKS,
    HardeningEvidenceInput,
    HardeningRunCreate,
    create_hardening_run,
    record_hardening_evidence,
)
from app.core.database import engine
from app.main import app
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, User
from app.models.platform import PlatformMembership, PlatformRoleEnum


def _owner(session: Session) -> AuthPrincipal:
    subject = str(uuid.uuid4())
    user = User(email=f"s20-{subject}@example.test", full_name="S20 Owner")
    session.add(user); session.flush()
    session.add(AuthIdentity(user_id=user.id, provider="supabase", provider_subject=subject, provider_email=user.email, email_verified=True))
    session.add(PlatformMembership(user_id=user.id, role=PlatformRoleEnum.PLATFORM_OWNER))
    session.commit()
    return AuthPrincipal(subject=subject, email=user.email, session_id=str(uuid.uuid4()), assurance_level="aal2", claims={"sub": subject, "aal": "aal2"}, provider="email")


PASS_OBSERVATIONS = {
    "isolation_matrix": {"denied_cross_tenant": 12, "contexts": ["tenant", "store", "terminal"]},
    "concurrency_matrix": {"lost_operations": 0, "duplicate_operations": 0, "contenders": 8},
    "retry_idempotency": {"lost_operations": 0, "duplicate_operations": 0, "retries": 20},
    "degraded_dependencies": {"capability_isolated": True, "core_available": True, "dependency": "tef_bridge"},
    "schema_migration": {"empty_db": True, "migrated_db": True, "no_drift": True},
    "backup_restore": {"restore_verified": True, "measured_rpo_minutes": 0, "measured_rto_minutes": 1},
    "incident_response": {"detected": True, "diagnosed": True, "recovered": True},
    "representative_load": {"samples": 500, "error_rate": 0.0, "p95_ms": 180},
    "auth_session": {"aal2_enforced": True, "pin_lockout": True, "terminal_revocation": True},
}


def test_s20_hardening_gate_requires_specific_measured_evidence():
    with Session(engine) as session:
        principal = _owner(session)
        projection = create_hardening_run(
            HardeningRunCreate(release_sha="65c4780", environment="ci", rpo_target_minutes=15, rto_target_minutes=60),
            principal,
            session,
        )
        run = projection["run"]
        assert projection["missing_checks"] == sorted(HARDENING_CHECKS)

        with pytest.raises(HTTPException) as invalid_restore:
            record_hardening_evidence(
                run.id,
                "backup_restore",
                HardeningEvidenceInput(status="PASS", evidence_ref="ci://restore/invalid", observed={"restore_verified": True, "measured_rpo_minutes": 16, "measured_rto_minutes": 1}),
                principal,
                session,
            )
        assert invalid_restore.value.status_code == 422

        blocked = record_hardening_evidence(
            run.id,
            "degraded_dependencies",
            HardeningEvidenceInput(status="BLOCKED", evidence_ref="incident://tef/unavailable", observed={"dependency": "tef_bridge", "reason": "not_homologated"}),
            principal,
            session,
        )
        assert blocked["run"].status == "BLOCKED"

        for key, observed in PASS_OBSERVATIONS.items():
            projection = record_hardening_evidence(
                run.id,
                key,
                HardeningEvidenceInput(status="PASS", evidence_ref=f"ci://s20/{key}", observed=observed),
                principal,
                session,
            )
        assert projection["run"].status == "PASSED"
        assert projection["missing_checks"] == []
        assert projection["run"].completed_at is not None


def test_s20_pass_cannot_be_declared_with_generic_or_empty_measurements():
    with Session(engine) as session:
        principal = _owner(session)
        run = create_hardening_run(HardeningRunCreate(release_sha="deadbee", environment="test"), principal, session)["run"]
        for key in HARDENING_CHECKS:
            with pytest.raises(HTTPException) as invalid:
                record_hardening_evidence(
                    run.id, key,
                    HardeningEvidenceInput(status="PASS", evidence_ref=f"ci://invalid/{key}", observed={"passed": True}),
                    principal, session,
                )
            assert invalid.value.status_code == 422


def test_s20_api_responses_are_not_cached_and_correlation_ids_are_sanitized():
    with TestClient(app) as client:
        response = client.get("/api/v1/control/health/components", headers={"X-Correlation-ID": "s20.valid-123"})
        assert response.headers["x-correlation-id"] == "s20.valid-123"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"

        rejected = client.get("/health", headers={"X-Correlation-ID": "invalid correlation id with spaces"})
        assert rejected.headers["x-correlation-id"] != "invalid correlation id with spaces"
