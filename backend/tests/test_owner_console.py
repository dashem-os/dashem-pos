import uuid

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.v1.endpoints.identity import (
    PlatformTenantCreate,
    PlatformTenantInvite,
    complete_owner_onboarding,
    complete_password_setup,
    get_me,
    platform_overview,
    platform_tenant_detail,
    invite_platform_tenant_user,
    provision_platform_tenant,
)
from app.core.database import engine
from app.core.security import AuthPrincipal
from app.models.identity import AuthIdentity, MembershipStatusEnum, RoleEnum, User
from app.models.platform import PlatformMembership, PlatformRoleEnum
from app.models.reliability import AuditEvent


def _principal(subject: str, assurance_level: str = "aal2") -> AuthPrincipal:
    return AuthPrincipal(
        subject=subject,
        email=f"owner-{subject}@example.test",
        session_id=str(uuid.uuid4()),
        assurance_level=assurance_level,
        claims={"sub": subject, "aal": assurance_level},
        provider="email",
    )


def _owner(session: Session) -> tuple[str, User]:
    subject = str(uuid.uuid4())
    user = User(email=f"owner-{subject}@example.test", full_name="Owner Test")
    session.add(user)
    session.flush()
    session.add(AuthIdentity(
        user_id=user.id,
        provider="supabase",
        provider_subject=subject,
        provider_email=user.email,
        email_verified=True,
    ))
    session.add(PlatformMembership(
        user_id=user.id,
        role=PlatformRoleEnum.PLATFORM_OWNER,
    ))
    session.commit()
    session.refresh(user)
    return subject, user


def test_owner_first_access_and_atomic_tenant_provisioning():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        subject, user = _owner(session)
        principal = _principal(subject)

        me_before = get_me(principal=principal, session=session)
        assert me_before["platform_role"] == PlatformRoleEnum.PLATFORM_OWNER
        assert me_before["password_setup_required"] is True
        assert me_before["mfa_required"] is False

        # First access and password recovery converge on this transition.
        # A retry must remain safe if the password was already updated.
        complete_password_setup(principal=principal, session=session)
        complete_password_setup(principal=principal, session=session)
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Tenant Owner {suffix}",
                slug=f"tenant-owner-{suffix}",
                first_store_name="Unidade Principal",
                first_store_code="matriz",
            ),
            principal=principal,
            session=session,
        )
        assert created.tenant.slug == f"tenant-owner-{suffix}"
        assert created.first_store.tenant_id == created.tenant.id
        assert created.first_store.code == "MATRIZ"

        audit = session.exec(
            select(AuditEvent).where(
                AuditEvent.actor_id == user.id,
                AuditEvent.tenant_id == created.tenant.id,
                AuditEvent.action == "platform.tenant.provisioned",
            )
        ).first()
        assert audit is not None
        assert audit.platform_scope is True

        complete_owner_onboarding(principal=principal, session=session)
        me_after = get_me(principal=principal, session=session)
        assert me_after["password_setup_required"] is False
        assert me_after["onboarding_completed"] is True

        overview = platform_overview(principal=principal, session=session)
        assert any(item.id == created.tenant.id and item.store_count == 1 for item in overview.tenants)


def test_owner_mutations_require_aal2():
    suffix = uuid.uuid4().hex[:8]
    with Session(engine) as session:
        subject, _ = _owner(session)
        principal = _principal(subject, assurance_level="aal1")
        with pytest.raises(HTTPException) as exc:
            provision_platform_tenant(
                data=PlatformTenantCreate(
                    name=f"Denied {suffix}",
                    slug=f"denied-{suffix}",
                    first_store_name="Principal",
                    first_store_code="MAIN",
                ),
                principal=principal,
                session=session,
            )
        assert exc.value.status_code == 403
        assert "Multi-factor" in exc.value.detail


def test_owner_can_open_tenant_and_invite_first_user(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    invite_subject = str(uuid.uuid4())
    with Session(engine) as session:
        owner_subject, _ = _owner(session)
        principal = _principal(owner_subject)
        complete_password_setup(principal=principal, session=session)
        created = provision_platform_tenant(
            data=PlatformTenantCreate(
                name=f"Invite Tenant {suffix}", slug=f"invite-{suffix}",
                first_store_name="Unidade Centro", first_store_code="CENTRO",
            ), principal=principal, session=session,
        )
        monkeypatch.setattr(
            "app.services.supabase_admin.invite_user",
            lambda **_: {"id": invite_subject, "email": f"user-{suffix}@example.test"},
        )
        result = invite_platform_tenant_user(
            tenant_id=created.tenant.id,
            data=PlatformTenantInvite(
                email=f"user-{suffix}@example.test", full_name="Tenant User",
                role=RoleEnum.TENANT_OWNER,
            ), principal=principal, session=session,
        )
        assert result.delivery_status == "ENVIADO"
        assert result.access.status == MembershipStatusEnum.INVITED

        detail = platform_tenant_detail(
            tenant_id=created.tenant.id, principal=principal, session=session,
        )
        assert len(detail.stores) == 1
        assert any(access.email == f"user-{suffix}@example.test" for access in detail.accesses)

        invited_principal = AuthPrincipal(
            subject=invite_subject, email=f"user-{suffix}@example.test",
            session_id=str(uuid.uuid4()), assurance_level="aal1",
            claims={"sub": invite_subject, "aal": "aal1"}, provider="email",
        )
        complete_password_setup(principal=invited_principal, session=session)
        invited_me = get_me(principal=invited_principal, session=session)
        assert invited_me["memberships"][0].status == MembershipStatusEnum.ACTIVE
