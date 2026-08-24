import json
import re
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func, or_, text
from sqlmodel import Session, select

from app.core.access import (
    get_platform_membership, get_request_user, require_platform_role,
    require_tenant_admin,
)
from app.core.database import get_session
from app.core.config import settings
from app.core.security import AuthPrincipal, get_current_principal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import (
    Membership, MembershipStatusEnum, RoleEnum, Store, Tenant, TenantStatusEnum, User,
    TenantProfile, TenantContact, TenantSubscription, ServicePlan,
    TenantCustomerTypeEnum, SubscriptionStatusEnum,
)
from app.models.platform import (
    Lead, LeadStatusEnum, PlatformRoleEnum, TenantCapability, CapabilityDefinition,
    CapabilityScopeEnum, CapabilityStatusEnum, EntitlementStatusEnum,
)
from app.models.reliability import AuditEvent, OutboxEvent, OutboxStatusEnum
from app.models.reliability import ServiceHeartbeat
from app.models.payment import CashSession, CashSessionStatusEnum, Register
from app.models.sale import Sale, SaleStatusEnum
from app.models.catalog import InventoryBalance, Product
from app.models.intelligence import AgentRun, AgentRunStatusEnum
from app.services import identity_service, reliability_service, supabase_admin
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, resolve_dependencies


router = APIRouter(dependencies=[Depends(get_current_principal)])
PLATFORM_MANAGERS = {PlatformRoleEnum.PLATFORM_OWNER, PlatformRoleEnum.PLATFORM_ADMIN}


def _digits(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"\D", "", value)
    return normalized or None


def _valid_cnpj(value: str) -> bool:
    if len(value) != 14 or value == value[0] * 14:
        return False
    numbers = [int(digit) for digit in value]
    for size in (12, 13):
        weights = list(range(size - 7, 1, -1)) + list(range(9, 1, -1))
        total = sum(number * weight for number, weight in zip(numbers[:size], weights))
        remainder = total % 11
        expected = 0 if remainder < 2 else 11 - remainder
        if numbers[size] != expected:
            return False
    return True


def _normalize_cnpj(value: Optional[str]) -> Optional[str]:
    normalized = _digits(value)
    if normalized and not _valid_cnpj(normalized):
        raise HTTPException(status_code=422, detail="Informe um CNPJ válido.")
    return normalized


def _profile_complete(profile: Optional[TenantProfile], contacts: list[TenantContact], stores: list[Store]) -> bool:
    if not profile:
        return False
    headquarters = next((store for store in stores if store.is_headquarters), None)
    primary = next((contact for contact in contacts if contact.is_primary and contact.is_active), None)
    return bool(
        profile.legal_name and profile.tax_id and profile.industry
        and profile.company_phone and primary and primary.full_name
        and headquarters and headquarters.postal_code and headquarters.street
        and headquarters.street_number and headquarters.city and headquarters.state
    )


def _tenant_read(
    tenant: Tenant,
    *,
    store_count: int,
    profile: Optional[TenantProfile] = None,
    contacts: Optional[list[TenantContact]] = None,
    stores: Optional[list[Store]] = None,
) -> "PlatformTenantRead":
    return PlatformTenantRead(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=getattr(tenant.status, "value", str(tenant.status)),
        created_at=tenant.created_at,
        store_count=store_count,
        customer_type=(
            getattr(profile.customer_type, "value", str(profile.customer_type))
            if profile else None
        ),
        legal_name=profile.legal_name if profile else tenant.legal_name,
        tax_id=profile.tax_id if profile else None,
        profile_complete=_profile_complete(profile, contacts or [], stores or []),
    )


class TenantCreate(BaseModel):
    name: str
    slug: str


class PlatformTenantCreate(BaseModel):
    name: str = PydanticField(min_length=2, max_length=160)
    slug: str = PydanticField(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    first_store_name: str = PydanticField(min_length=2, max_length=160)
    first_store_code: str = PydanticField(min_length=2, max_length=40)
    customer_type: TenantCustomerTypeEnum = TenantCustomerTypeEnum.TEST
    legal_name: Optional[str] = PydanticField(default=None, min_length=2, max_length=200)
    tax_id: Optional[str] = PydanticField(default=None, max_length=18)
    state_registration: Optional[str] = PydanticField(default=None, max_length=32)
    municipal_registration: Optional[str] = PydanticField(default=None, max_length=32)
    industry: Optional[str] = PydanticField(default=None, max_length=120)
    company_email: Optional[str] = PydanticField(default=None, max_length=254)
    company_phone: Optional[str] = PydanticField(default=None, max_length=32)
    website: Optional[str] = PydanticField(default=None, max_length=255)
    contact_name: Optional[str] = PydanticField(default=None, max_length=160)
    contact_job_title: Optional[str] = PydanticField(default=None, max_length=120)
    contact_email: Optional[str] = PydanticField(default=None, max_length=254)
    contact_phone: Optional[str] = PydanticField(default=None, max_length=32)
    postal_code: Optional[str] = PydanticField(default=None, max_length=10)
    street: Optional[str] = PydanticField(default=None, max_length=200)
    street_number: Optional[str] = PydanticField(default=None, max_length=32)
    address_complement: Optional[str] = PydanticField(default=None, max_length=120)
    district: Optional[str] = PydanticField(default=None, max_length=120)
    city: Optional[str] = PydanticField(default=None, max_length=120)
    state: Optional[str] = PydanticField(default=None, max_length=2)
    plan_id: Optional[uuid.UUID] = None


class PlatformTenantRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    store_count: int
    customer_type: Optional[str] = None
    legal_name: Optional[str] = None
    tax_id: Optional[str] = None
    profile_complete: bool = False


class PlatformOverview(BaseModel):
    tenant_count: int
    trial_count: int
    active_count: int
    lead_count: int
    tenants: List[PlatformTenantRead]


class PlatformTenantProvisioned(BaseModel):
    tenant: Tenant
    first_store: Store


class PlatformTenantAccessRead(BaseModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    email: Optional[str] = None
    full_name: str
    role: str
    status: str
    store_id: Optional[uuid.UUID] = None
    store_name: Optional[str] = None
    created_at: datetime


class PlatformTenantDetail(BaseModel):
    tenant: PlatformTenantRead
    profile: Optional[TenantProfile] = None
    contacts: List[TenantContact]
    subscription: Optional[TenantSubscription] = None
    plan: Optional[ServicePlan] = None
    stores: List[Store]
    accesses: List[PlatformTenantAccessRead]
    capabilities: List[TenantCapability]


class HealthComponent(BaseModel):
    key: str
    label: str
    status: str
    latency_ms: Optional[float] = None
    details: dict[str, Any] = PydanticField(default_factory=dict)


class PlatformSystemHealth(BaseModel):
    checked_at: datetime
    status: str
    components: List[HealthComponent]
    totals: dict[str, int]


class TenantDailyMetric(BaseModel):
    date: date
    sales_count: int
    revenue: Decimal


class TenantOperationalMetrics(BaseModel):
    tenant_id: uuid.UUID
    checked_at: datetime
    status: str
    stores_total: int
    stores_active: int
    users_total: int
    users_active: int
    users_invited: int
    users_suspended: int
    users_revoked: int
    registers_active: int
    cash_sessions_open: int
    products_total: int
    low_stock_items: int
    sales_today: int
    sales_30d: int
    revenue_today: Decimal
    revenue_30d: Decimal
    outbox_pending: int
    outbox_failed: int
    agent_runs_30d: int
    agent_failures_30d: int
    last_activity_at: Optional[datetime]
    daily: List[TenantDailyMetric]


class CapabilityCatalogItem(BaseModel):
    key: str
    name: str
    version: str
    scope: str
    description: str
    requires: List[str]
    enabled: bool
    status: str
    contract_limits: dict[str, Any]


class TenantCapabilityUpdate(BaseModel):
    enabled: bool
    contract_limits: dict[str, Any] = PydanticField(default_factory=dict)
    reason: str = PydanticField(min_length=4, max_length=500)


class PlatformTenantProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = PydanticField(min_length=2, max_length=160)
    customer_type: TenantCustomerTypeEnum
    legal_name: Optional[str] = PydanticField(default=None, max_length=200)
    tax_id: Optional[str] = PydanticField(default=None, max_length=18)
    state_registration: Optional[str] = PydanticField(default=None, max_length=32)
    municipal_registration: Optional[str] = PydanticField(default=None, max_length=32)
    industry: Optional[str] = PydanticField(default=None, max_length=120)
    company_email: Optional[str] = PydanticField(default=None, max_length=254)
    company_phone: Optional[str] = PydanticField(default=None, max_length=32)
    website: Optional[str] = PydanticField(default=None, max_length=255)
    notes: Optional[str] = None
    contact_name: Optional[str] = PydanticField(default=None, max_length=160)
    contact_job_title: Optional[str] = PydanticField(default=None, max_length=120)
    contact_email: Optional[str] = PydanticField(default=None, max_length=254)
    contact_phone: Optional[str] = PydanticField(default=None, max_length=32)
    store_name: Optional[str] = PydanticField(default=None, max_length=160)
    store_code: Optional[str] = PydanticField(default=None, max_length=40)
    postal_code: Optional[str] = PydanticField(default=None, max_length=10)
    street: Optional[str] = PydanticField(default=None, max_length=200)
    street_number: Optional[str] = PydanticField(default=None, max_length=32)
    address_complement: Optional[str] = PydanticField(default=None, max_length=120)
    district: Optional[str] = PydanticField(default=None, max_length=120)
    city: Optional[str] = PydanticField(default=None, max_length=120)
    state: Optional[str] = PydanticField(default=None, max_length=2)


class PlatformTenantLifecycleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TenantStatusEnum
    reason: str = PydanticField(min_length=3, max_length=500)


class ServicePlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = PydanticField(min_length=2, max_length=60, pattern=r"^[A-Z0-9_-]+$")
    name: str = PydanticField(min_length=2, max_length=120)
    description: Optional[str] = None
    store_limit: Optional[int] = PydanticField(default=None, ge=1)
    user_limit: Optional[int] = PydanticField(default=None, ge=1)
    terminal_limit: Optional[int] = PydanticField(default=None, ge=1)


class TenantSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: Optional[uuid.UUID] = None
    status: SubscriptionStatusEnum


class PlatformStoreCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = PydanticField(min_length=2, max_length=160)
    code: str = PydanticField(min_length=2, max_length=40, pattern=r"^[A-Z0-9_-]+$")
    site_type: str = PydanticField(default="BRANCH", max_length=32)
    tax_id: Optional[str] = PydanticField(default=None, max_length=18)
    state_registration: Optional[str] = PydanticField(default=None, max_length=32)
    email: Optional[str] = PydanticField(default=None, max_length=254)
    phone: Optional[str] = PydanticField(default=None, max_length=32)
    postal_code: Optional[str] = PydanticField(default=None, max_length=10)
    street: Optional[str] = PydanticField(default=None, max_length=200)
    street_number: Optional[str] = PydanticField(default=None, max_length=32)
    address_complement: Optional[str] = PydanticField(default=None, max_length=120)
    district: Optional[str] = PydanticField(default=None, max_length=120)
    city: Optional[str] = PydanticField(default=None, max_length=120)
    state: Optional[str] = PydanticField(default=None, max_length=2)


class PlatformStoreUpdate(PlatformStoreCreate):
    is_active: bool = True


class PlatformTenantAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: RoleEnum
    status: MembershipStatusEnum
    store_id: Optional[uuid.UUID] = None
    reason: str = PydanticField(min_length=3, max_length=500)


class PlatformTenantInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = PydanticField(min_length=5, max_length=254)
    full_name: str = PydanticField(min_length=2, max_length=160)
    role: RoleEnum = RoleEnum.TENANT_OWNER
    store_id: Optional[uuid.UUID] = None


class PlatformTenantInviteResult(BaseModel):
    access: PlatformTenantAccessRead
    delivery_status: str


class StoreCreate(BaseModel):
    tenant_id: uuid.UUID
    name: str
    code: str


class UserCreate(BaseModel):
    email: str
    full_name: str
    provider_subject: Optional[str] = None
    password: Optional[str] = None  # ignored; temporary request compatibility only


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: Optional[str] = None
    full_name: str
    is_active: bool


class MembershipCreate(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: Optional[uuid.UUID] = None
    role: RoleEnum


class TestMutationRequest(BaseModel):
    tenant_id: uuid.UUID
    store_id: uuid.UUID
    actor_id: uuid.UUID
    action_name: str
    payload_data: str


def _platform_or_tenant_admin(
    session: Session, principal: AuthPrincipal, tenant_id: uuid.UUID
) -> None:
    if principal.bypass:
        set_tenant_db_context(session, tenant_id, user_id=principal.legacy_user_id)
        return
    platform = get_platform_membership(session, principal)
    if platform and PlatformRoleEnum(platform.role) in PLATFORM_MANAGERS:
        require_platform_role(session, principal, PLATFORM_MANAGERS)
        return
    require_tenant_admin(session, principal, tenant_id)


@router.get("/me")
def get_me(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = get_request_user(session, principal)
    if principal.bypass and not user:
        return {"mode": "local-bypass", "user": None, "platform_role": None, "memberships": []}
    assert user is not None
    membership_query = select(Membership).where(
        Membership.user_id == user.id,
        Membership.status == MembershipStatusEnum.ACTIVE,
    )
    if principal.provider == "operational":
        try:
            tenant_id = uuid.UUID(str(principal.claims["tenant_id"]))
            store_id = uuid.UUID(str(principal.claims["store_id"]))
            membership_id = uuid.UUID(str(principal.claims["membership_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="Operational session has an invalid scope.") from exc
        # /identity/me has no scope headers. The signed operational token is
        # therefore the only authoritative source used to open the RLS window.
        set_tenant_db_context(session, tenant_id, store_id, user.id)
        membership_query = membership_query.where(
            Membership.id == membership_id,
            Membership.tenant_id == tenant_id,
            Membership.store_id == store_id,
        )
        platform = None
    else:
        platform = get_platform_membership(session, principal)
    memberships = session.exec(membership_query).all()
    return {
        "mode": "authenticated",
        "user": UserRead.model_validate(user),
        "platform_role": platform.role if platform else None,
        "memberships": memberships,
        "assurance_level": principal.assurance_level,
        "auth_provider": principal.provider,
        "password_setup_required": principal.provider == "email" and user.password_setup_completed_at is None,
        "mfa_required": bool(
            platform
            and PlatformRoleEnum(platform.role) in PLATFORM_MANAGERS
            and principal.assurance_level != "aal2"
        ),
        "onboarding_completed": user.onboarding_completed_at is not None,
    }


@router.post("/me/password-setup-complete", response_model=UserRead)
def complete_password_setup(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = get_request_user(session, principal)
    assert user is not None
    if principal.provider != "email":
        raise HTTPException(status_code=409, detail="Password setup is not required for this provider.")
    return identity_service.mark_password_setup_completed(session, user)


@router.post("/me/onboarding-complete", response_model=UserRead)
def complete_owner_onboarding(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = require_platform_role(
        session, principal, PLATFORM_MANAGERS, require_aal2=True
    )
    assert user is not None
    if principal.provider == "email" and user.password_setup_completed_at is None:
        raise HTTPException(status_code=409, detail="Password setup is required first.")
    return identity_service.mark_onboarding_completed(session, user)


@router.get("/platform/overview", response_model=PlatformOverview)
def platform_overview(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    tenants = session.exec(select(Tenant).order_by(Tenant.created_at.desc())).all()
    stores = session.exec(select(Store)).all()
    profiles = session.exec(select(TenantProfile)).all()
    contacts = session.exec(select(TenantContact).where(TenantContact.is_active == True)).all()  # noqa: E712
    profile_map = {profile.tenant_id: profile for profile in profiles}
    contact_map: dict[uuid.UUID, list[TenantContact]] = {}
    store_map: dict[uuid.UUID, list[Store]] = {}
    for contact in contacts:
        contact_map.setdefault(contact.tenant_id, []).append(contact)
    store_counts: dict[uuid.UUID, int] = {}
    for store in stores:
        store_counts[store.tenant_id] = store_counts.get(store.tenant_id, 0) + 1
        store_map.setdefault(store.tenant_id, []).append(store)
    leads = session.exec(select(Lead).where(Lead.status != LeadStatusEnum.LOST)).all()
    return PlatformOverview(
        tenant_count=len(tenants),
        trial_count=sum(1 for tenant in tenants if tenant.status == TenantStatusEnum.TRIAL),
        active_count=sum(1 for tenant in tenants if tenant.status == TenantStatusEnum.ACTIVE),
        lead_count=len(leads),
        tenants=[
            _tenant_read(
                tenant,
                store_count=store_counts.get(tenant.id, 0),
                profile=profile_map.get(tenant.id),
                contacts=contact_map.get(tenant.id, []),
                stores=store_map.get(tenant.id, []),
            )
            for tenant in tenants
        ],
    )


def _count(session: Session, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(session.exec(statement).one() or 0)


@router.get("/platform/health", response_model=PlatformSystemHealth)
def platform_system_health(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    checked_at = datetime.utcnow()
    components: list[HealthComponent] = [
        HealthComponent(key="api", label="Backend API", status="HEALTHY", details={"version": settings.VERSION}),
    ]

    started = time.perf_counter()
    try:
        session.exec(text("SELECT 1")).one()
        latency = round((time.perf_counter() - started) * 1000, 2)
        components.append(HealthComponent(
            key="database", label="PostgreSQL", status="HEALTHY", latency_ms=latency,
            details={"pool_size": settings.DB_POOL_SIZE, "max_overflow": settings.DB_MAX_OVERFLOW},
        ))
    except Exception as exc:
        components.append(HealthComponent(
            key="database", label="PostgreSQL", status="UNHEALTHY",
            details={"error": str(exc)[:300]},
        ))

    pending = _count(session, OutboxEvent, OutboxEvent.status.in_({OutboxStatusEnum.PENDING, OutboxStatusEnum.PROCESSING}))
    failed = _count(session, OutboxEvent, OutboxEvent.status == OutboxStatusEnum.FAILED)
    components.append(HealthComponent(
        key="outbox", label="Fila transacional", status="DEGRADED" if failed else "HEALTHY",
        details={"pending": pending, "failed": failed},
    ))

    heartbeat = session.get(ServiceHeartbeat, "outbox_worker")
    heartbeat_age = (checked_at - heartbeat.last_seen_at).total_seconds() if heartbeat else None
    worker_status = (
        "HEALTHY" if heartbeat and heartbeat_age is not None and heartbeat_age <= 90 and heartbeat.status == "HEALTHY"
        else "DEGRADED" if heartbeat else "UNKNOWN"
    )
    components.append(HealthComponent(
        key="worker", label="Outbox worker", status=worker_status,
        details={
            "last_seen_at": heartbeat.last_seen_at.isoformat() if heartbeat else None,
            "age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
            **(heartbeat.details if heartbeat else {}),
        },
    ))

    if not settings.SUPABASE_URL:
        components.append(HealthComponent(
            key="auth", label="Supabase Auth", status="NOT_CONFIGURED", details={},
        ))
    else:
        auth_started = time.perf_counter()
        try:
            response = httpx.get(f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/health", timeout=2.5)
            auth_latency = round((time.perf_counter() - auth_started) * 1000, 2)
            components.append(HealthComponent(
                key="auth", label="Supabase Auth",
                status="HEALTHY" if response.status_code < 400 else "DEGRADED",
                latency_ms=auth_latency, details={"http_status": response.status_code},
            ))
        except Exception as exc:
            components.append(HealthComponent(
                key="auth", label="Supabase Auth", status="UNHEALTHY",
                details={"error": str(exc)[:300]},
            ))

    unhealthy = any(item.status == "UNHEALTHY" for item in components)
    attention = any(item.status in {"DEGRADED", "UNKNOWN", "NOT_CONFIGURED"} for item in components)
    overall = "UNHEALTHY" if unhealthy else "DEGRADED" if attention else "HEALTHY"
    return PlatformSystemHealth(
        checked_at=checked_at,
        status=overall,
        components=components,
        totals={
            "tenants": _count(session, Tenant),
            "active_stores": _count(session, Store, Store.is_active == True),  # noqa: E712
            "active_users": _count(session, User, User.is_active == True),  # noqa: E712
            "open_cash_sessions": _count(session, CashSession, CashSession.status == CashSessionStatusEnum.OPEN),
            "pending_outbox": pending,
            "failed_outbox": failed,
        },
    )


@router.get("/platform/tenants/{tenant_id}/metrics", response_model=TenantOperationalMetrics)
def platform_tenant_metrics(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    now = datetime.utcnow()
    today = datetime(now.year, now.month, now.day)
    since_30d = today - timedelta(days=29)
    memberships = session.exec(select(Membership).where(Membership.tenant_id == tenant_id)).all()
    access_counts = {status.value: 0 for status in MembershipStatusEnum}
    for membership in memberships:
        access_counts[getattr(membership.status, "value", str(membership.status))] += 1

    paid_statuses = {SaleStatusEnum.PAID, SaleStatusEnum.COMPLETED}
    sale_rows = session.exec(
        select(
            func.date(Sale.created_at),
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.net_total), 0),
        ).where(
            Sale.tenant_id == tenant_id,
            Sale.created_at >= since_30d,
            Sale.status.in_(paid_statuses),
        ).group_by(func.date(Sale.created_at)).order_by(func.date(Sale.created_at))
    ).all()
    by_date = {
        row[0]: (int(row[1]), Decimal(str(row[2] or 0))) for row in sale_rows
    }
    daily = []
    for offset in range(30):
        current = (since_30d + timedelta(days=offset)).date()
        count, revenue = by_date.get(current, (0, Decimal("0")))
        daily.append(TenantDailyMetric(date=current, sales_count=count, revenue=revenue))

    sales_today = sum(item.sales_count for item in daily if item.date == today.date())
    revenue_today = sum((item.revenue for item in daily if item.date == today.date()), Decimal("0"))
    sales_30d = sum(item.sales_count for item in daily)
    revenue_30d = sum((item.revenue for item in daily), Decimal("0"))
    outbox_pending = _count(session, OutboxEvent, OutboxEvent.tenant_id == tenant_id, OutboxEvent.status.in_({OutboxStatusEnum.PENDING, OutboxStatusEnum.PROCESSING}))
    outbox_failed = _count(session, OutboxEvent, OutboxEvent.tenant_id == tenant_id, OutboxEvent.status == OutboxStatusEnum.FAILED)
    agent_runs = _count(session, AgentRun, AgentRun.tenant_id == tenant_id, AgentRun.created_at >= since_30d)
    agent_failures = _count(session, AgentRun, AgentRun.tenant_id == tenant_id, AgentRun.created_at >= since_30d, AgentRun.status == AgentRunStatusEnum.FAILED)
    last_sale = session.exec(select(func.max(Sale.created_at)).where(Sale.tenant_id == tenant_id)).one()
    last_audit = session.exec(select(func.max(AuditEvent.created_at)).where(AuditEvent.tenant_id == tenant_id)).one()
    last_activity = max((value for value in (last_sale, last_audit) if value is not None), default=None)
    status = "DEGRADED" if outbox_failed or access_counts[MembershipStatusEnum.ACTIVE.value] == 0 else "HEALTHY"
    return TenantOperationalMetrics(
        tenant_id=tenant_id, checked_at=now, status=status,
        stores_total=_count(session, Store, Store.tenant_id == tenant_id),
        stores_active=_count(session, Store, Store.tenant_id == tenant_id, Store.is_active == True),  # noqa: E712
        users_total=len(memberships),
        users_active=access_counts[MembershipStatusEnum.ACTIVE.value],
        users_invited=access_counts[MembershipStatusEnum.INVITED.value],
        users_suspended=access_counts[MembershipStatusEnum.SUSPENDED.value],
        users_revoked=access_counts[MembershipStatusEnum.REVOKED.value],
        registers_active=_count(session, Register, Register.tenant_id == tenant_id, Register.is_active == True),  # noqa: E712
        cash_sessions_open=_count(session, CashSession, CashSession.tenant_id == tenant_id, CashSession.status == CashSessionStatusEnum.OPEN),
        products_total=_count(session, Product, Product.tenant_id == tenant_id),
        low_stock_items=_count(session, InventoryBalance, InventoryBalance.tenant_id == tenant_id, InventoryBalance.quantity <= InventoryBalance.minimum_stock),
        sales_today=sales_today, sales_30d=sales_30d,
        revenue_today=revenue_today, revenue_30d=revenue_30d,
        outbox_pending=outbox_pending, outbox_failed=outbox_failed,
        agent_runs_30d=agent_runs, agent_failures_30d=agent_failures,
        last_activity_at=last_activity, daily=daily,
    )


@router.post("/platform/tenants", response_model=PlatformTenantProvisioned, status_code=201)
def provision_platform_tenant(
    data: PlatformTenantCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = require_platform_role(
        session, principal, PLATFORM_MANAGERS, require_aal2=True
    )
    assert user is not None
    tax_id = _normalize_cnpj(data.tax_id)
    if data.plan_id and session.get(ServicePlan, data.plan_id) is None:
        raise HTTPException(status_code=422, detail="Plano não encontrado.")
    tenant, store = identity_service.provision_tenant(
        session,
        name=data.name.strip(),
        slug=data.slug,
        first_store_name=data.first_store_name.strip(),
        first_store_code=data.first_store_code.strip().upper(),
        actor_id=user.id,
        customer_type=data.customer_type,
        legal_name=data.legal_name.strip() if data.legal_name else None,
        tax_id=tax_id,
        state_registration=data.state_registration.strip() if data.state_registration else None,
        municipal_registration=data.municipal_registration.strip() if data.municipal_registration else None,
        industry=data.industry.strip() if data.industry else None,
        company_email=data.company_email.strip().lower() if data.company_email else None,
        company_phone=data.company_phone.strip() if data.company_phone else None,
        website=data.website.strip() if data.website else None,
        contact_name=data.contact_name.strip() if data.contact_name else None,
        contact_job_title=data.contact_job_title.strip() if data.contact_job_title else None,
        contact_email=data.contact_email.strip().lower() if data.contact_email else None,
        contact_phone=data.contact_phone.strip() if data.contact_phone else None,
        postal_code=_digits(data.postal_code),
        street=data.street.strip() if data.street else None,
        street_number=data.street_number.strip() if data.street_number else None,
        address_complement=data.address_complement.strip() if data.address_complement else None,
        district=data.district.strip() if data.district else None,
        city=data.city.strip() if data.city else None,
        state=data.state.strip().upper() if data.state else None,
        plan_id=data.plan_id,
    )
    return PlatformTenantProvisioned(tenant=tenant, first_store=store)


def _tenant_access_read(membership: Membership, user: User, store: Optional[Store]) -> PlatformTenantAccessRead:
    return PlatformTenantAccessRead(
        membership_id=membership.id, user_id=user.id, email=user.email,
        full_name=user.full_name, role=getattr(membership.role, "value", str(membership.role)),
        status=getattr(membership.status, "value", str(membership.status)),
        store_id=membership.store_id, store_name=store.name if store else None,
        created_at=membership.created_at,
    )


@router.get("/platform/tenants/{tenant_id}", response_model=PlatformTenantDetail)
def platform_tenant_detail(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    stores = session.exec(select(Store).where(Store.tenant_id == tenant_id)).all()
    profile = session.get(TenantProfile, tenant_id)
    contacts = session.exec(
        select(TenantContact).where(TenantContact.tenant_id == tenant_id).order_by(TenantContact.is_primary.desc(), TenantContact.full_name)
    ).all()
    subscription = session.get(TenantSubscription, tenant_id)
    plan = session.get(ServicePlan, subscription.plan_id) if subscription and subscription.plan_id else None
    capabilities = session.exec(
        select(TenantCapability).where(TenantCapability.tenant_id == tenant_id).order_by(TenantCapability.key)
    ).all()
    store_map = {store.id: store for store in stores}
    rows = session.exec(
        select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.tenant_id == tenant_id)
    ).all()
    return PlatformTenantDetail(
        tenant=_tenant_read(
            tenant, store_count=len(stores), profile=profile, contacts=list(contacts), stores=list(stores),
        ),
        profile=profile,
        contacts=list(contacts),
        subscription=subscription,
        plan=plan,
        stores=stores,
        accesses=[_tenant_access_read(membership, user, store_map.get(membership.store_id)) for membership, user in rows],
        capabilities=list(capabilities),
    )


@router.put("/platform/tenants/{tenant_id}/profile", response_model=TenantProfile)
def update_platform_tenant_profile(
    tenant_id: uuid.UUID,
    data: PlatformTenantProfileUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    profile = session.get(TenantProfile, tenant_id) or TenantProfile(
        tenant_id=tenant_id,
        customer_type=data.customer_type,
        trade_name=data.name.strip(),
    )
    normalized_tax_id = _normalize_cnpj(data.tax_id)
    if normalized_tax_id:
        duplicate = session.exec(select(TenantProfile).where(
            TenantProfile.tax_id == normalized_tax_id,
            TenantProfile.tenant_id != tenant_id,
        )).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Este CNPJ já pertence a outro cliente.")
    previous_type = getattr(profile.customer_type, "value", str(profile.customer_type))
    tenant.name = data.name.strip()
    tenant.legal_name = data.legal_name.strip() if data.legal_name else None
    tenant.updated_at = datetime.utcnow()
    profile.customer_type = data.customer_type
    profile.trade_name = tenant.name
    profile.legal_name = tenant.legal_name
    profile.tax_id = normalized_tax_id
    profile.state_registration = data.state_registration.strip() if data.state_registration else None
    profile.municipal_registration = data.municipal_registration.strip() if data.municipal_registration else None
    profile.industry = data.industry.strip() if data.industry else None
    profile.company_email = data.company_email.strip().lower() if data.company_email else None
    profile.company_phone = data.company_phone.strip() if data.company_phone else None
    profile.website = data.website.strip() if data.website else None
    profile.notes = data.notes.strip() if data.notes else None
    profile.updated_at = datetime.utcnow()
    primary_contact = session.exec(select(TenantContact).where(
        TenantContact.tenant_id == tenant_id,
        TenantContact.is_primary == True,  # noqa: E712
        TenantContact.is_active == True,  # noqa: E712
    )).first()
    if data.contact_name:
        primary_contact = primary_contact or TenantContact(
            tenant_id=tenant_id, full_name=data.contact_name.strip(), is_primary=True,
        )
        primary_contact.full_name = data.contact_name.strip()
        primary_contact.job_title = data.contact_job_title.strip() if data.contact_job_title else None
        primary_contact.email = data.contact_email.strip().lower() if data.contact_email else None
        primary_contact.phone = data.contact_phone.strip() if data.contact_phone else None
        primary_contact.updated_at = datetime.utcnow()
        session.add(primary_contact)
    headquarters = session.exec(select(Store).where(
        Store.tenant_id == tenant_id,
        Store.is_headquarters == True,  # noqa: E712
    )).first()
    if headquarters:
        if data.store_name:
            headquarters.name = data.store_name.strip()
        if data.store_code:
            headquarters.code = data.store_code.strip().upper()
        headquarters.postal_code = _digits(data.postal_code)
        headquarters.street = data.street.strip() if data.street else None
        headquarters.street_number = data.street_number.strip() if data.street_number else None
        headquarters.address_complement = data.address_complement.strip() if data.address_complement else None
        headquarters.district = data.district.strip() if data.district else None
        headquarters.city = data.city.strip() if data.city else None
        headquarters.state = data.state.strip().upper() if data.state else None
        headquarters.updated_at = datetime.utcnow()
        session.add(headquarters)
    session.add(tenant)
    session.add(profile)
    payload = {
        "tenant_id": str(tenant_id),
        "changed_by": str(actor.id),
        "customer_type_from": previous_type,
        "customer_type_to": data.customer_type.value,
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.tenant.profile_updated", target=f"tenant:{tenant_id}",
        audit_payload=payload, aggregate_type="tenant", aggregate_id=str(tenant_id),
        event_type="platform.tenant.profile_updated", outbox_payload=payload,
    )
    session.commit()
    session.refresh(profile)
    return profile


@router.patch("/platform/tenants/{tenant_id}/lifecycle", response_model=Tenant)
def update_platform_tenant_lifecycle(
    tenant_id: uuid.UUID,
    data: PlatformTenantLifecycleUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    previous = getattr(tenant.status, "value", str(tenant.status))
    if previous == data.status.value:
        raise HTTPException(status_code=409, detail="O cliente já está neste estado.")
    tenant.status = data.status
    tenant.updated_at = datetime.utcnow()
    session.add(tenant)
    payload = {
        "tenant_id": str(tenant_id), "from": previous, "to": data.status.value,
        "reason": data.reason.strip(), "actor_id": str(actor.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.tenant.lifecycle_changed", target=f"tenant:{tenant_id}",
        audit_payload=payload, aggregate_type="tenant", aggregate_id=str(tenant_id),
        event_type="platform.tenant.lifecycle_changed", outbox_payload=payload,
    )
    session.commit()
    session.refresh(tenant)
    return tenant


@router.get("/platform/plans", response_model=List[ServicePlan])
def list_service_plans(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return list(session.exec(select(ServicePlan).order_by(ServicePlan.name)).all())


@router.post("/platform/plans", response_model=ServicePlan, status_code=201)
def create_service_plan(
    data: ServicePlanCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    code = data.code.strip().upper()
    if session.exec(select(ServicePlan).where(ServicePlan.code == code)).first():
        raise HTTPException(status_code=409, detail="Já existe um plano com este código.")
    plan = ServicePlan(
        code=code, name=data.name.strip(), description=data.description,
        store_limit=data.store_limit, user_limit=data.user_limit,
        terminal_limit=data.terminal_limit,
    )
    session.add(plan)
    session.flush()
    session.add(AuditEvent(
        actor_id=actor.id, tenant_id=None, store_id=None, platform_scope=True,
        action="platform.plan.created", target=f"service_plan:{plan.id}",
        payload=json.dumps({"plan_id": str(plan.id), "code": plan.code}),
    ))
    session.commit()
    session.refresh(plan)
    return plan


@router.put("/platform/tenants/{tenant_id}/subscription", response_model=TenantSubscription)
def update_tenant_subscription(
    tenant_id: uuid.UUID,
    data: TenantSubscriptionUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    if data.plan_id and session.get(ServicePlan, data.plan_id) is None:
        raise HTTPException(status_code=422, detail="Plano não encontrado.")
    subscription = session.get(TenantSubscription, tenant_id) or TenantSubscription(tenant_id=tenant_id)
    subscription.plan_id = data.plan_id
    subscription.status = data.status
    subscription.updated_at = datetime.utcnow()
    session.add(subscription)
    payload = {
        "tenant_id": str(tenant_id), "plan_id": str(data.plan_id) if data.plan_id else None,
        "status": data.status.value, "actor_id": str(actor.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.tenant.subscription_updated", target=f"tenant:{tenant_id}",
        audit_payload=payload, aggregate_type="tenant_subscription", aggregate_id=str(tenant_id),
        event_type="platform.tenant.subscription_updated", outbox_payload=payload,
    )
    session.commit()
    session.refresh(subscription)
    return subscription


def _ensure_capability_definition(session: Session, key: str) -> CapabilityDefinition:
    contract = CAPABILITY_REGISTRY[key]
    definition = session.get(CapabilityDefinition, key)
    if definition is None:
        definition = CapabilityDefinition(
            key=contract.key,
            name=contract.name,
            version=contract.version,
            description=contract.description,
            scope=CapabilityScopeEnum(contract.scope.value),
            status=CapabilityStatusEnum.ACTIVE,
            configuration_schema=dict(contract.configuration_schema),
        )
    else:
        definition.name = contract.name
        definition.version = contract.version
        definition.description = contract.description
        definition.scope = CapabilityScopeEnum(contract.scope.value)
        definition.status = CapabilityStatusEnum.ACTIVE
        definition.configuration_schema = dict(contract.configuration_schema)
        definition.updated_at = datetime.utcnow()
    session.add(definition)
    return definition


@router.get(
    "/platform/tenants/{tenant_id}/capabilities",
    response_model=List[CapabilityCatalogItem],
)
def tenant_capability_catalog(
    tenant_id: uuid.UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    entitlements = {
        item.key: item for item in session.exec(
            select(TenantCapability).where(TenantCapability.tenant_id == tenant_id)
        ).all()
    }
    return [
        CapabilityCatalogItem(
            key=contract.key,
            name=contract.name,
            version=contract.version,
            scope=contract.scope.value,
            description=contract.description,
            requires=list(contract.requires),
            enabled=bool(entitlements.get(key) and entitlements[key].enabled),
            status=(
                getattr(entitlements[key].status, "value", str(entitlements[key].status))
                if key in entitlements else EntitlementStatusEnum.SUSPENDED.value
            ),
            contract_limits=dict(entitlements[key].contract_limits) if key in entitlements else {},
        )
        for key, contract in CAPABILITY_REGISTRY.items()
    ]


@router.put(
    "/platform/tenants/{tenant_id}/capabilities/{capability_key}",
    response_model=List[CapabilityCatalogItem],
)
def update_tenant_capability(
    tenant_id: uuid.UUID,
    capability_key: str,
    data: TenantCapabilityUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    if capability_key not in CAPABILITY_REGISTRY:
        raise HTTPException(status_code=404, detail="Capacidade não encontrada no catálogo.")

    existing = {
        item.key: item for item in session.exec(
            select(TenantCapability).where(TenantCapability.tenant_id == tenant_id)
        ).all()
    }
    changed_keys: list[str] = []
    if data.enabled:
        for key in resolve_dependencies([capability_key]):
            _ensure_capability_definition(session, key)
        session.flush()
        for key in resolve_dependencies([capability_key]):
            entitlement = existing.get(key) or TenantCapability(tenant_id=tenant_id, key=key)
            entitlement.enabled = True
            entitlement.status = EntitlementStatusEnum.ACTIVE
            if key == capability_key:
                entitlement.contract_limits = data.contract_limits
            entitlement.updated_at = datetime.utcnow()
            session.add(entitlement)
            existing[key] = entitlement
            changed_keys.append(key)
    else:
        blockers = [
            contract.name for key, contract in CAPABILITY_REGISTRY.items()
            if key != capability_key
            and existing.get(key) is not None
            and existing[key].enabled
            and capability_key in contract.requires
        ]
        if blockers:
            raise HTTPException(
                status_code=409,
                detail=f"Desative primeiro as capacidades dependentes: {', '.join(blockers)}.",
            )
        entitlement = existing.get(capability_key)
        if entitlement is not None:
            entitlement.enabled = False
            entitlement.status = EntitlementStatusEnum.SUSPENDED
            entitlement.contract_limits = data.contract_limits
            entitlement.updated_at = datetime.utcnow()
            session.add(entitlement)
        changed_keys.append(capability_key)

    payload = {
        "tenant_id": str(tenant_id),
        "capability_key": capability_key,
        "enabled": data.enabled,
        "changed_keys": changed_keys,
        "reason": data.reason.strip(),
        "actor_id": str(actor.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.tenant.capability_updated",
        target=f"tenant:{tenant_id}:capability:{capability_key}",
        audit_payload=payload, aggregate_type="tenant_capability",
        aggregate_id=f"{tenant_id}:{capability_key}",
        event_type="platform.tenant.capability_updated", outbox_payload=payload,
    )
    session.commit()
    return tenant_capability_catalog(tenant_id, principal, session)


@router.post("/platform/tenants/{tenant_id}/invitations", response_model=PlatformTenantInviteResult, status_code=201)
def invite_platform_tenant_user(
    tenant_id: uuid.UUID,
    data: PlatformTenantInvite,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    if data.role not in {RoleEnum.TENANT_OWNER, RoleEnum.OWNER} or data.store_id is not None:
        raise HTTPException(
            status_code=403,
            detail="Dashem Control entrega somente o administrador contratual do tenant.",
        )
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Informe um e-mail válido.")
    store = None
    if data.store_id is not None:
        store = session.get(Store, data.store_id)
        if not store or store.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="A unidade informada não pertence ao cliente.")
    if data.role in {RoleEnum.CASHIER, RoleEnum.OPERATOR} and store is None:
        raise HTTPException(status_code=422, detail="Este papel exige uma unidade específica.")

    existing_user = session.exec(select(User).where(User.email == email)).first()
    if existing_user:
        existing_membership = session.exec(select(Membership).where(
            Membership.user_id == existing_user.id,
            Membership.tenant_id == tenant_id,
        )).first()
        if existing_membership:
            raise HTTPException(status_code=409, detail="Este usuário já possui acesso ao tenant.")
    provider_subject = None
    delivery_status = "IDENTIDADE_EXISTENTE"
    if existing_user is None:
        invited = supabase_admin.invite_user(email=email, full_name=data.full_name.strip(), tenant_id=str(tenant_id))
        provider_subject = str(invited["id"])
        delivery_status = "ENVIADO"
    membership = identity_service.provision_tenant_access(
        session, tenant=tenant, email=email, full_name=data.full_name,
        role=data.role, store_id=data.store_id, actor_id=actor.id,
        provider_subject=provider_subject,
    )
    user = session.get(User, membership.user_id)
    assert user is not None
    return PlatformTenantInviteResult(
        access=_tenant_access_read(membership, user, store), delivery_status=delivery_status,
    )


@router.patch("/platform/tenants/{tenant_id}/accesses/{membership_id}", response_model=PlatformTenantAccessRead)
def update_platform_tenant_access(
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    data: PlatformTenantAccessUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    membership = session.get(Membership, membership_id)
    if not membership or membership.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Acesso não encontrado.")
    if data.role != membership.role or data.store_id != membership.store_id:
        raise HTTPException(
            status_code=403,
            detail="Dashem Control pode executar ações de segurança, mas papéis e escopos pertencem ao Tenant Admin.",
        )
    store = None
    if data.store_id is not None:
        store = session.get(Store, data.store_id)
        if not store or store.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="A unidade informada não pertence ao cliente.")
    if data.role in {RoleEnum.CASHIER, RoleEnum.OPERATOR} and store is None:
        raise HTTPException(status_code=422, detail="Este papel exige uma unidade específica.")
    removing_owner = (
        membership.role in {RoleEnum.TENANT_OWNER, RoleEnum.OWNER}
        and membership.status in {MembershipStatusEnum.ACTIVE, MembershipStatusEnum.INVITED}
        and (
            data.role not in {RoleEnum.TENANT_OWNER, RoleEnum.OWNER}
            or data.status in {MembershipStatusEnum.SUSPENDED, MembershipStatusEnum.REVOKED}
        )
    )
    if removing_owner:
        other_owners = session.exec(select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.id != membership_id,
            Membership.role.in_({RoleEnum.TENANT_OWNER, RoleEnum.OWNER}),
            Membership.status.in_({MembershipStatusEnum.ACTIVE, MembershipStatusEnum.INVITED}),
        )).all()
        if not other_owners:
            raise HTTPException(status_code=409, detail="Conceda outro acesso Owner antes de remover o último administrador.")
    previous = {
        "role": getattr(membership.role, "value", str(membership.role)),
        "status": getattr(membership.status, "value", str(membership.status)),
        "store_id": str(membership.store_id) if membership.store_id else None,
    }
    membership.role = data.role
    membership.status = data.status
    membership.store_id = data.store_id
    membership.updated_at = datetime.utcnow()
    session.add(membership)
    payload = {
        "tenant_id": str(tenant_id), "membership_id": str(membership_id),
        "previous": previous,
        "current": {"role": data.role.value, "status": data.status.value, "store_id": str(data.store_id) if data.store_id else None},
        "reason": data.reason.strip(), "actor_id": str(actor.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=data.store_id, actor_id=actor.id,
        action="platform.tenant.access_updated", target=f"membership:{membership_id}",
        audit_payload=payload, aggregate_type="membership", aggregate_id=str(membership_id),
        event_type="platform.tenant.access_updated", outbox_payload=payload,
    )
    session.commit()
    session.refresh(membership)
    user = session.get(User, membership.user_id)
    assert user is not None
    return _tenant_access_read(membership, user, store)


def _apply_store_fields(store: Store, data: PlatformStoreCreate) -> None:
    store.name = data.name.strip()
    store.code = data.code.strip().upper()
    store.site_type = data.site_type.strip().upper()
    store.tax_id = _normalize_cnpj(data.tax_id)
    store.state_registration = data.state_registration.strip() if data.state_registration else None
    store.email = data.email.strip().lower() if data.email else None
    store.phone = data.phone.strip() if data.phone else None
    store.postal_code = _digits(data.postal_code)
    store.street = data.street.strip() if data.street else None
    store.street_number = data.street_number.strip() if data.street_number else None
    store.address_complement = data.address_complement.strip() if data.address_complement else None
    store.district = data.district.strip() if data.district else None
    store.city = data.city.strip() if data.city else None
    store.state = data.state.strip().upper() if data.state else None
    store.updated_at = datetime.utcnow()


@router.post("/platform/tenants/{tenant_id}/stores", response_model=Store, status_code=201)
def create_platform_store(
    tenant_id: uuid.UUID,
    data: PlatformStoreCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    if session.exec(select(Store).where(Store.tenant_id == tenant_id, Store.code == data.code)).first():
        raise HTTPException(status_code=409, detail="Já existe uma unidade com este código.")
    store = Store(tenant_id=tenant_id, name=data.name.strip(), code=data.code.strip().upper(), is_headquarters=False)
    _apply_store_fields(store, data)
    session.add(store)
    session.flush()
    payload = {"tenant_id": str(tenant_id), "store_id": str(store.id), "code": store.code, "actor_id": str(actor.id)}
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=store.id, actor_id=actor.id,
        action="platform.tenant.store_created", target=f"store:{store.id}",
        audit_payload=payload, aggregate_type="store", aggregate_id=str(store.id),
        event_type="platform.tenant.store_created", outbox_payload=payload,
    )
    session.commit(); session.refresh(store)
    return store


@router.put("/platform/tenants/{tenant_id}/stores/{store_id}", response_model=Store)
def update_platform_store(
    tenant_id: uuid.UUID,
    store_id: uuid.UUID,
    data: PlatformStoreUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    store = session.get(Store, store_id)
    if not store or store.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    duplicate = session.exec(select(Store).where(
        Store.tenant_id == tenant_id, Store.code == data.code, Store.id != store_id,
    )).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Já existe uma unidade com este código.")
    _apply_store_fields(store, data)
    store.is_active = data.is_active
    session.add(store)
    payload = {"tenant_id": str(tenant_id), "store_id": str(store.id), "active": store.is_active, "actor_id": str(actor.id)}
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=store.id, actor_id=actor.id,
        action="platform.tenant.store_updated", target=f"store:{store.id}",
        audit_payload=payload, aggregate_type="store", aggregate_id=str(store.id),
        event_type="platform.tenant.store_updated", outbox_payload=payload,
    )
    session.commit(); session.refresh(store)
    return store


@router.post("/tenants", response_model=Tenant)
def create_tenant_endpoint(
    data: TenantCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return identity_service.create_tenant(session, name=data.name, slug=data.slug)


@router.get("/tenants", response_model=List[Tenant])
def list_tenants(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    platform = get_platform_membership(session, principal)
    if principal.bypass:
        set_platform_db_context(session, principal.legacy_user_id)
        return session.exec(select(Tenant)).all()
    if platform:
        require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
        return session.exec(select(Tenant)).all()
    user = get_request_user(session, principal)
    assert user is not None
    return session.exec(
        select(Tenant).join(Membership).where(
            Membership.user_id == user.id,
            Membership.status == MembershipStatusEnum.ACTIVE,
        ).distinct()
    ).all()


@router.post("/stores", response_model=Store)
def create_store_endpoint(
    data: StoreCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _platform_or_tenant_admin(session, principal, data.tenant_id)
    return identity_service.create_store(session, data.tenant_id, data.name, data.code)


@router.get("/stores", response_model=List[Store])
def list_stores(
    tenant_id: Optional[uuid.UUID] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    if principal.bypass:
        set_platform_db_context(session, principal.legacy_user_id)
        query = select(Store)
        return session.exec(query.where(Store.tenant_id == tenant_id) if tenant_id else query).all()
    if get_platform_membership(session, principal):
        require_platform_role(session, principal, PLATFORM_MANAGERS)
        query = select(Store)
        return session.exec(query.where(Store.tenant_id == tenant_id) if tenant_id else query).all()
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant_id is required.")
    user = get_request_user(session, principal)
    assert user is not None
    set_tenant_db_context(session, tenant_id, user_id=user.id)
    memberships = session.exec(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant_id,
            Membership.status == MembershipStatusEnum.ACTIVE,
        )
    ).all()
    if not memberships:
        raise HTTPException(status_code=403, detail="No active membership for this tenant.")
    if any(m.store_id is None for m in memberships):
        return session.exec(select(Store).where(Store.tenant_id == tenant_id)).all()
    allowed_store_ids = [m.store_id for m in memberships if m.store_id]
    return session.exec(
        select(Store).where(Store.tenant_id == tenant_id, Store.id.in_(allowed_store_ids))
    ).all()


@router.post("/users", response_model=UserRead)
def create_user_endpoint(
    data: UserCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return identity_service.create_user(session, data.email, data.full_name, data.provider_subject)


@router.get("/users", response_model=List[UserRead])
def list_users(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS)
    return session.exec(select(User)).all()


@router.post("/memberships", response_model=Membership)
def create_membership_endpoint(
    data: MembershipCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    _platform_or_tenant_admin(session, principal, data.tenant_id)
    return identity_service.create_membership(
        session, data.user_id, data.tenant_id, data.store_id, data.role
    )


@router.get("/memberships", response_model=List[Membership])
def list_memberships(
    user_id: Optional[uuid.UUID] = None,
    tenant_id: Optional[uuid.UUID] = None,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    if tenant_id:
        _platform_or_tenant_admin(session, principal, tenant_id)
    else:
        require_platform_role(session, principal, PLATFORM_MANAGERS)
    query = select(Membership)
    if user_id:
        query = query.where(Membership.user_id == user_id)
    if tenant_id:
        query = query.where(Membership.tenant_id == tenant_id)
    return session.exec(query).all()


@router.post("/test-atomic-mutation", include_in_schema=False)
def test_atomic_mutation_endpoint(
    data: TestMutationRequest,
    x_idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_correlation_id: Optional[str] = Header(None, alias="X-Correlation-ID"),
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    if not principal.bypass:
        raise HTTPException(status_code=404, detail="Not found.")
    set_tenant_db_context(session, data.tenant_id, data.store_id, data.actor_id)
    if x_idempotency_key:
        is_cached, status_code, body = reliability_service.check_idempotency(
            session, data.tenant_id, data.actor_id, "POST /test-atomic-mutation",
            x_idempotency_key, data.model_dump(),
        )
        if is_cached and status_code and body:
            return body
    audit, outbox = reliability_service.write_audit_and_outbox(
        session=session, tenant_id=data.tenant_id, store_id=data.store_id,
        actor_id=data.actor_id, action=data.action_name,
        target=f"MUTATION-{uuid.uuid4().hex[:6]}",
        audit_payload={"data": data.payload_data}, aggregate_type="test_aggregate",
        aggregate_id=str(uuid.uuid4()), event_type="test.mutated",
        outbox_payload={"data": data.payload_data}, correlation_id=x_correlation_id,
    )
    response = {"status": "success", "audit_id": str(audit.id), "outbox_id": str(outbox.id), "correlation_id": x_correlation_id}
    if x_idempotency_key:
        response = reliability_service.save_idempotency_record(
            session, data.tenant_id, data.actor_id, "POST /test-atomic-mutation",
            x_idempotency_key, data.model_dump(), 200, response,
        )
    session.commit()
    return response
