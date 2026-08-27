import uuid
import json
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select
from fastapi import HTTPException, status
from app.models.identity import (
    AuthIdentity, Tenant, TenantStatusEnum, Store, User, Membership,
    MembershipStatusEnum, RoleEnum, TenantProfile, TenantContact,
    TenantSubscription, TenantCustomerTypeEnum, SubscriptionStatusEnum,
)
from app.models.reliability import AuditEvent, OutboxEvent, OutboxStatusEnum

def create_tenant(session: Session, name: str, slug: str) -> Tenant:
    existing = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant with slug '{slug}' already exists."
        )
    tenant = Tenant(name=name, slug=slug, status=TenantStatusEnum.TRIAL)
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant


def provision_tenant(
    session: Session,
    *,
    name: str,
    slug: str,
    first_store_name: str,
    first_store_code: str,
    actor_id: uuid.UUID,
    customer_type: TenantCustomerTypeEnum = TenantCustomerTypeEnum.TEST,
    legal_name: Optional[str] = None,
    tax_id: Optional[str] = None,
    state_registration: Optional[str] = None,
    municipal_registration: Optional[str] = None,
    industry: Optional[str] = None,
    company_email: Optional[str] = None,
    company_phone: Optional[str] = None,
    website: Optional[str] = None,
    contact_name: Optional[str] = None,
    contact_job_title: Optional[str] = None,
    contact_email: Optional[str] = None,
    contact_phone: Optional[str] = None,
    store_tax_id: Optional[str] = None,
    store_state_registration: Optional[str] = None,
    store_email: Optional[str] = None,
    store_phone: Optional[str] = None,
    postal_code: Optional[str] = None,
    street: Optional[str] = None,
    street_number: Optional[str] = None,
    address_complement: Optional[str] = None,
    district: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    plan_id: Optional[uuid.UUID] = None,
    commit: bool = True,
) -> tuple[Tenant, Store]:
    """Create the tenant and its first site in one audited transaction."""
    existing = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with slug '{slug}' already exists.",
        )

    tenant = Tenant(
        name=name,
        slug=slug,
        legal_name=legal_name,
        status=TenantStatusEnum.TRIAL,
    )
    session.add(tenant)
    session.flush()
    profile = TenantProfile(
        tenant_id=tenant.id,
        customer_type=customer_type,
        trade_name=name,
        legal_name=legal_name,
        tax_id=tax_id,
        state_registration=state_registration,
        municipal_registration=municipal_registration,
        industry=industry,
        company_email=company_email,
        company_phone=company_phone,
        website=website,
    )
    session.add(profile)
    if contact_name:
        session.add(TenantContact(
            tenant_id=tenant.id,
            full_name=contact_name,
            job_title=contact_job_title,
            email=contact_email,
            phone=contact_phone,
            is_primary=True,
        ))
    session.add(TenantSubscription(
        tenant_id=tenant.id,
        plan_id=plan_id,
        status=(
            SubscriptionStatusEnum.TRIAL
            if customer_type in {TenantCustomerTypeEnum.TEST, TenantCustomerTypeEnum.PILOT}
            else SubscriptionStatusEnum.PENDING
        ),
    ))
    store = Store(
        tenant_id=tenant.id,
        name=first_store_name,
        code=first_store_code,
        site_type="HEADQUARTERS",
        is_headquarters=True,
        legal_name=legal_name,
        tax_id=store_tax_id or tax_id,
        state_registration=store_state_registration or state_registration,
        email=store_email or company_email,
        phone=store_phone or company_phone,
        postal_code=postal_code,
        street=street,
        street_number=street_number,
        address_complement=address_complement,
        district=district,
        city=city,
        state=state,
    )
    session.add(store)
    session.flush()

    event_payload = {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "slug": tenant.slug,
        "store_id": str(store.id),
        "store_name": store.name,
        "store_code": store.code,
        "customer_type": customer_type.value,
        "profile_complete": bool(legal_name and tax_id and industry and contact_name and city and state),
        "plan_id": str(plan_id) if plan_id else None,
    }
    session.add(AuditEvent(
        actor_id=actor_id,
        tenant_id=tenant.id,
        store_id=store.id,
        platform_scope=True,
        action="platform.tenant.provisioned",
        target=f"tenant:{tenant.id}",
        payload=json.dumps(event_payload),
    ))
    session.add(OutboxEvent(
        tenant_id=tenant.id,
        store_id=store.id,
        actor_id=actor_id,
        aggregate_type="tenant",
        aggregate_id=str(tenant.id),
        event_type="platform.tenant.provisioned",
        payload=json.dumps(event_payload),
        status=OutboxStatusEnum.PENDING,
    ))
    if commit:
        session.commit()
        session.refresh(tenant)
        session.refresh(store)
    return tenant, store


def mark_password_setup_completed(session: Session, user: User) -> User:
    changed = False
    if user.password_setup_completed_at is None:
        user.password_setup_completed_at = datetime.utcnow()
        session.add(user)
        changed = True
    invited_memberships = session.exec(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.status == MembershipStatusEnum.INVITED,
        )
    ).all()
    for membership in invited_memberships:
        membership.status = MembershipStatusEnum.ACTIVE
        membership.updated_at = datetime.utcnow()
        session.add(membership)
        changed = True
    if changed:
        session.commit()
        session.refresh(user)
    return user


def provision_tenant_access(
    session: Session,
    *,
    tenant: Tenant,
    email: str,
    full_name: str,
    role: RoleEnum,
    store_id: Optional[uuid.UUID],
    actor_id: uuid.UUID,
    provider_subject: Optional[str],
    audit_scope: str = "platform",
    commit: bool = True,
) -> Membership:
    """Provision one tenant access without ever accepting credentials locally."""
    normalized_email = email.strip().lower()
    user = session.exec(select(User).where(User.email == normalized_email)).first()
    if user is None:
        if not provider_subject:
            raise HTTPException(status_code=502, detail="O provedor não retornou a identidade convidada.")
        user = User(email=normalized_email, full_name=full_name.strip())
        session.add(user)
        session.flush()
        session.add(AuthIdentity(
            user_id=user.id,
            provider="supabase",
            provider_subject=provider_subject,
            provider_email=normalized_email,
            email_verified=False,
        ))
        membership_status = MembershipStatusEnum.INVITED
    else:
        membership_status = MembershipStatusEnum.ACTIVE

    existing = session.exec(select(Membership).where(
        Membership.user_id == user.id,
        Membership.tenant_id == tenant.id,
    )).first()
    if existing:
        raise HTTPException(status_code=409, detail="Este usuário já possui acesso ao tenant.")

    membership = Membership(
        user_id=user.id,
        tenant_id=tenant.id,
        store_id=store_id,
        role=role,
        status=membership_status,
    )
    session.add(membership)
    session.flush()
    payload = {
        "tenant_id": str(tenant.id), "user_id": str(user.id), "email": normalized_email,
        "membership_id": str(membership.id), "role": role.value, "store_id": str(store_id) if store_id else None,
    }
    session.add(AuditEvent(
        actor_id=actor_id, tenant_id=tenant.id, store_id=store_id, platform_scope=audit_scope == "platform",
        action=f"{audit_scope}.tenant.user_invited", target=f"membership:{membership.id}",
        payload=json.dumps(payload),
    ))
    session.add(OutboxEvent(
        tenant_id=tenant.id, store_id=store_id, actor_id=actor_id,
        aggregate_type="membership", aggregate_id=str(membership.id),
        event_type=f"{audit_scope}.tenant.user_invited", payload=json.dumps(payload),
        status=OutboxStatusEnum.PENDING,
    ))
    if commit:
        session.commit()
        session.refresh(membership)
    return membership


def mark_onboarding_completed(session: Session, user: User) -> User:
    if user.onboarding_completed_at is None:
        user.onboarding_completed_at = datetime.utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
    return user

def create_store(session: Session, tenant_id: uuid.UUID, name: str, code: str) -> Store:
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found."
        )
    existing = session.exec(
        select(Store).where(Store.tenant_id == tenant_id, Store.code == code)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Store code '{code}' already exists in this tenant."
        )

    store = Store(tenant_id=tenant_id, name=name, code=code)
    session.add(store)
    session.commit()
    session.refresh(store)
    return store

def create_user(
    session: Session,
    email: str,
    full_name: str,
    provider_subject: Optional[str] = None,
) -> User:
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{email}' already exists."
        )
    user = User(email=email, full_name=full_name)
    session.add(user)
    session.flush()
    if provider_subject:
        session.add(AuthIdentity(
            user_id=user.id,
            provider="supabase",
            provider_subject=provider_subject,
            provider_email=email,
        ))
    session.commit()
    session.refresh(user)
    return user

def create_membership(
    session: Session,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID],
    role: RoleEnum
) -> Membership:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found."
        )

    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found."
        )

    # A membership without store_id is tenant-wide. A site-scoped membership
    # must always point to a site owned by the same tenant.
    if store_id is not None:
        store = session.get(Store, store_id)
        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found."
            )
        if store.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Store '{store_id}' does not belong to Tenant '{tenant_id}'."
            )

    if role in {RoleEnum.CASHIER, RoleEnum.OPERATOR} and store_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{role.value}' requires a store-scoped membership."
        )
    
    # Check UNIQUE constraint
    existing = session.exec(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
            Membership.store_id == store_id
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Membership already exists for this User, Tenant, and Store."
        )

    membership = Membership(
        user_id=user_id,
        tenant_id=tenant_id,
        store_id=store_id,
        role=role
    )
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership
