import json
import re
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func, or_, text, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.access import (
    get_platform_membership, get_request_user, require_platform_permission, require_platform_role,
    require_tenant_admin,
)
from app.core.database import get_session
from app.core.config import settings
from app.core.security import AuthPrincipal, get_current_principal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.identity import (
    Membership, MembershipStatusEnum, RoleEnum, Store, Tenant, TenantStatusEnum, User,
    TenantProfile, TenantContact, TenantSubscription, ServicePlan, ServicePlanRevision,
    TenantCustomerTypeEnum, TenantTypeEnum, TenantPhaseEnum, SubscriptionStatusEnum,
)
from app.models.platform import (
    Lead, LeadStatusEnum, PlatformRoleEnum, TenantCapability, CapabilityDefinition,
    CapabilityScopeEnum, CapabilityStatusEnum, EntitlementStatusEnum,
    IdentityDeliveryEvent, TenantContract, TenantProfileAssignment,
    CapabilityProfileRevision,
)
from app.models.owner_finance import (
    SaasBillingAccount, SaasInvoice, SaasInvoiceStatusEnum,
    SaasPaymentAllocation, SaasRefund,
)
from app.models.commercial_catalog import CommercialActivity, CommercialActivityCapability
from app.models.reliability import AuditEvent, OutboxEvent, OutboxStatusEnum
from app.models.reliability import ServiceHeartbeat
from app.services import commercial_pricing, identity_service, reliability_service, supabase_admin
from app.services.commercial_offer_service import (
    ActivityRule, CommercialOfferError, compose_commercial_offer,
)
from app.services.contract_entitlement_service import (
    build_entitlement_snapshot, latest_contract, resolve_contract_entitlements,
)
from app.services.quota_policy_service import (
    QuotaCapacityExceededError,
    require_count_capacity,
    tenant_count_quota_read_model,
)
from app.services.storage_quota_service import storage_quota_read_model
from app.modules.governance.contracts import CountResource
from app.modules.capabilities.registry import CAPABILITY_REGISTRY, IMPLEMENTED_CAPABILITIES, resolve_dependencies
from app.modules.capabilities.niches import (
    BusinessNiche, NICHE_CONTRACTS, capability_payload,
    selected_entitlement_keys,
)


router = APIRouter(dependencies=[Depends(get_current_principal)])
PLATFORM_MANAGERS = {PlatformRoleEnum.PLATFORM_OWNER, PlatformRoleEnum.PLATFORM_ADMIN}
FINANCE_READ = "control.finance.read"
FINANCE_MANAGE_BILLING = "control.finance.manage_billing"


def _commercial_terms(subscription: TenantSubscription, billing: "OwnerBillingCreate") -> None:
    gross = Decimal(billing.monthly_amount).quantize(Decimal("0.01"))
    discount = billing.discount
    if discount is None:
        subscription.gross_monthly_amount = gross
        subscription.discount_type = None
        subscription.discount_value = Decimal("0.0000")
        subscription.discount_amount = Decimal("0.00")
        subscription.discount_reason_code = None
        subscription.discount_reason = None
        subscription.discount_starts_on = None
        subscription.discount_ends_on = None
        subscription.discount_review_on = None
        subscription.monthly_amount = gross
        return
    commercial_pricing.validate_discount_dates(
        starts_on=discount.starts_on,
        ends_on=discount.ends_on,
        review_on=discount.review_on,
    )
    is_full_discount = (
        discount.type == ContractDiscountType.PERCENTAGE
        and discount.value >= Decimal("100")
    ) or (
        discount.type == ContractDiscountType.FIXED
        and discount.value >= gross
    )
    if is_full_discount and discount.ends_on is None and discount.review_on is None:
        raise HTTPException(
            status_code=422,
            detail="Desconto de 100% exige data final ou data de revisão.",
        )
    discount_amount = commercial_pricing.calculate_discount(
        gross_amount=gross,
        discount_type=discount.type.value,
        discount_value=discount.value,
        starts_on=discount.starts_on,
        ends_on=discount.ends_on,
        effective_on=date.today(),
    )
    subscription.gross_monthly_amount = gross
    subscription.discount_type = discount.type.value
    subscription.discount_value = discount.value
    subscription.discount_amount = discount_amount
    subscription.discount_reason_code = discount.reason_code.value
    subscription.discount_reason = discount.reason.strip()
    subscription.discount_starts_on = discount.starts_on
    subscription.discount_ends_on = discount.ends_on
    subscription.discount_review_on = discount.review_on
    subscription.monthly_amount = (gross - discount_amount).quantize(Decimal("0.01"))


def _snapshot_plan(
    session: Session, *, plan: ServicePlan, actor_id: uuid.UUID, reason: str
) -> ServicePlanRevision:
    revision = ServicePlanRevision(
        plan_id=plan.id,
        version=plan.version,
        code=plan.code,
        name=plan.name,
        description=plan.description,
        is_active=plan.is_active,
        store_limit=plan.store_limit,
        user_limit=plan.user_limit,
        terminal_limit=plan.terminal_limit,
        storage_limit_mb=plan.storage_limit_mb,
        capability_keys=list(plan.capability_keys),
        activity_keys=list(plan.activity_keys),
        monthly_price=plan.monthly_price,
        reason=reason.strip(),
        created_by=actor_id,
    )
    session.add(revision)
    session.flush()
    return revision


def _current_plan_revision(session: Session, plan: ServicePlan) -> ServicePlanRevision:
    revision = session.exec(select(ServicePlanRevision).where(
        ServicePlanRevision.plan_id == plan.id,
        ServicePlanRevision.version == plan.version,
    )).first()
    if revision is None:
        raise HTTPException(status_code=409, detail="A versão atual do plano não possui snapshot comercial.")
    return revision


def _billing_contract_snapshot(billing: "OwnerBillingCreate", subscription: TenantSubscription) -> dict[str, Any]:
    return {
        "contact_name": billing.contact_name.strip(),
        "email": billing.email.strip().lower(),
        "phone": billing.phone.strip() if billing.phone else None,
        "gross_monthly_amount": str(subscription.gross_monthly_amount),
        "discount_type": subscription.discount_type,
        "discount_value": str(subscription.discount_value),
        "discount_amount": str(subscription.discount_amount),
        "discount_reason_code": subscription.discount_reason_code,
        "discount_reason": subscription.discount_reason,
        "discount_starts_on": subscription.discount_starts_on.isoformat() if subscription.discount_starts_on else None,
        "discount_ends_on": subscription.discount_ends_on.isoformat() if subscription.discount_ends_on else None,
        "discount_review_on": subscription.discount_review_on.isoformat() if subscription.discount_review_on else None,
        "monthly_amount": str(subscription.monthly_amount),
        "billing_day": billing.billing_day,
    }


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


def _valid_cpf(value: str) -> bool:
    if len(value) != 11 or value == value[0] * 11:
        return False
    numbers = [int(digit) for digit in value]
    first = (sum(number * weight for number, weight in zip(numbers[:9], range(10, 1, -1))) * 10) % 11
    first = 0 if first == 10 else first
    second = (sum(number * weight for number, weight in zip(numbers[:10], range(11, 1, -1))) * 10) % 11
    second = 0 if second == 10 else second
    return numbers[9] == first and numbers[10] == second


def _normalize_tax_id(value: Optional[str]) -> Optional[str]:
    normalized = _digits(value)
    if normalized and not (
        (len(normalized) == 11 and _valid_cpf(normalized))
        or (len(normalized) == 14 and _valid_cnpj(normalized))
    ):
        raise HTTPException(status_code=422, detail="Informe um CPF ou CNPJ válido.")
    return normalized


def _legacy_customer_type(tenant_type: TenantTypeEnum, phase: TenantPhaseEnum) -> TenantCustomerTypeEnum:
    if tenant_type == TenantTypeEnum.INTERNAL:
        return TenantCustomerTypeEnum.INTERNAL
    if phase == TenantPhaseEnum.PILOT:
        return TenantCustomerTypeEnum.PILOT
    if phase == TenantPhaseEnum.PRODUCTION:
        return TenantCustomerTypeEnum.CUSTOMER
    return TenantCustomerTypeEnum.TEST


def _profile_complete(profile: Optional[TenantProfile], contacts: list[TenantContact], stores: list[Store]) -> bool:
    if not profile:
        return False
    headquarters = next((store for store in stores if store.is_headquarters), None)
    primary = next((contact for contact in contacts if contact.is_primary and contact.is_active), None)
    return bool(
        profile.legal_name and profile.tax_id
        and profile.company_phone and primary and primary.full_name
        and headquarters and headquarters.postal_code and headquarters.street
        and headquarters.street_number and headquarters.city and headquarters.state
    )


def _tenant_read(
    tenant: Tenant,
    *,
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
        customer_type=(
            getattr(profile.customer_type, "value", str(profile.customer_type))
            if profile else None
        ),
        tenant_type=(getattr(profile.tenant_type, "value", str(profile.tenant_type)) if profile else None),
        lifecycle_phase=(
            getattr(profile.lifecycle_phase, "value", str(profile.lifecycle_phase)) if profile else None
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


class OwnerQuotaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: int = PydanticField(ge=1)
    devices: int = PydanticField(ge=1)
    units: int = PydanticField(ge=1)
    storage_mb: int = PydanticField(ge=128)


class OwnerInitialAdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = PydanticField(min_length=2, max_length=160)
    email: str = PydanticField(min_length=5, max_length=254)


class ContractDiscountType(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


class ContractDiscountReason(str, Enum):
    INTERNAL_CONTROLLED_TEST = "INTERNAL_CONTROLLED_TEST"
    COMMERCIAL_PILOT = "COMMERCIAL_PILOT"
    LAUNCH_PROMOTION = "LAUNCH_PROMOTION"
    PARTNERSHIP = "PARTNERSHIP"
    RETENTION = "RETENTION"
    COMMERCIAL_NEGOTIATION = "COMMERCIAL_NEGOTIATION"
    SERVICE_COMPENSATION = "SERVICE_COMPENSATION"


class CapabilitySelectionMode(str, Enum):
    OFFER_DEFAULT = "OFFER_DEFAULT"
    EXPLICIT = "EXPLICIT"


class OwnerContractDiscount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ContractDiscountType
    value: Decimal = PydanticField(gt=0)
    reason_code: ContractDiscountReason
    reason: str = PydanticField(min_length=4, max_length=500)
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    review_on: Optional[date] = None


class OwnerBillingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_name: str = PydanticField(min_length=2, max_length=160)
    email: str = PydanticField(min_length=5, max_length=254)
    phone: Optional[str] = PydanticField(default=None, max_length=32)
    monthly_amount: Decimal = PydanticField(default=Decimal("0.00"), ge=0)
    billing_day: int = PydanticField(ge=1, le=28)
    discount: Optional[OwnerContractDiscount] = None


class OwnerTenantProvisionCreate(PlatformTenantCreate):
    """The only public Owner onboarding contract.

    Unlike the lower-level tenant primitive, every commercial decision needed
    to produce a coherent tenant is mandatory here.
    """

    model_config = ConfigDict(extra="forbid")

    legal_name: str = PydanticField(min_length=2, max_length=200)
    tax_id: str = PydanticField(min_length=11, max_length=18)
    company_phone: str = PydanticField(min_length=8, max_length=32)
    contact_name: str = PydanticField(min_length=2, max_length=160)
    contact_email: str = PydanticField(min_length=5, max_length=254)
    postal_code: str = PydanticField(min_length=8, max_length=10)
    street: str = PydanticField(min_length=2, max_length=200)
    street_number: str = PydanticField(min_length=1, max_length=32)
    district: str = PydanticField(min_length=2, max_length=120)
    city: str = PydanticField(min_length=2, max_length=120)
    state: str = PydanticField(min_length=2, max_length=2)
    plan_id: uuid.UUID
    tenant_type: TenantTypeEnum = TenantTypeEnum.CUSTOMER
    lifecycle_phase: TenantPhaseEnum = TenantPhaseEnum.PILOT
    niches: List[BusinessNiche] = PydanticField(min_length=1)
    quotas: OwnerQuotaCreate
    capability_keys: List[str] = PydanticField(default_factory=list)
    capability_selection_mode: CapabilitySelectionMode
    billing: OwnerBillingCreate
    initial_admin: OwnerInitialAdminCreate


class OwnerNicheRead(BaseModel):
    key: str
    name: str
    description: str
    required_capabilities: List[dict[str, Any]]
    allowed_addons: List[dict[str, Any]]


class PlatformTenantRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    customer_type: Optional[str] = None
    tenant_type: Optional[str] = None
    lifecycle_phase: Optional[str] = None
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
    niche: Optional[BusinessNiche] = None
    niches: List[BusinessNiche] = PydanticField(default_factory=list)
    contract: Optional[TenantContract] = None
    initial_admin: Optional["PlatformTenantAccessRead"] = None
    delivery_status: Optional[str] = None


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


class PlatformTenantResourceUsage(BaseModel):
    resource: str
    contracted: Optional[int] = None
    configured: int
    reserved: int
    occupied: int
    available: Optional[int] = None
    decision: str
    reason: str
    measured_at: datetime


class PlatformStorageProviderCapacity(BaseModel):
    provider: str
    configured: bool
    capacity_bytes: Optional[int] = None
    reserved_margin_bytes: int
    used_bytes: Optional[int] = None
    reserved_bytes: int
    occupied_bytes: Optional[int] = None
    available_bytes: Optional[int] = None
    object_count: Optional[int] = None
    measurement_status: str
    decision: str
    reason: str
    measured_at: Optional[datetime] = None
    managed_buckets: List[str] = PydanticField(default_factory=list)
    egress_measurement_status: str
    egress_reason: str


class PlatformTenantStorageUsage(BaseModel):
    resource: str
    contracted_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    reserved_bytes: int
    occupied_bytes: Optional[int] = None
    available_bytes: Optional[int] = None
    object_count: Optional[int] = None
    measurement_status: str
    decision: str
    reason: str
    measured_at: Optional[datetime] = None
    watermark: Optional[str] = None
    measurement_id: Optional[uuid.UUID] = None
    source_keys: List[str] = PydanticField(default_factory=list)
    enforcement_active: bool
    provider_capacity: PlatformStorageProviderCapacity


class PlatformTenantDetail(BaseModel):
    tenant: PlatformTenantRead
    profile: Optional[TenantProfile] = None
    contacts: List[TenantContact]
    subscription: Optional[TenantSubscription] = None
    plan: Optional[ServicePlan] = None
    stores: List[Store]
    accesses: List[PlatformTenantAccessRead]
    capabilities: List[TenantCapability]
    niche: Optional[BusinessNiche] = None
    niches: List[BusinessNiche] = PydanticField(default_factory=list)
    contract: Optional[TenantContract] = None
    billing_account: Optional[SaasBillingAccount] = None
    resource_usage: dict[str, PlatformTenantResourceUsage] = PydanticField(default_factory=dict)
    storage_usage: PlatformTenantStorageUsage


class HealthComponent(BaseModel):
    key: str
    label: str
    status: str
    latency_ms: Optional[float] = None
    details: dict[str, Any] = PydanticField(default_factory=dict)


class PlatformHealthTotals(BaseModel):
    tenants: int
    pending_outbox: int
    failed_outbox: int


class PlatformSystemHealth(BaseModel):
    checked_at: datetime
    status: str
    components: List[HealthComponent]
    totals: PlatformHealthTotals


class PlatformFinanceSubscription(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    plan_name: Optional[str] = None
    subscription_status: SubscriptionStatusEnum
    monthly_amount: Decimal
    gross_monthly_amount: Decimal
    discount_amount: Decimal
    discount_reason_code: Optional[str] = None
    discount_ends_on: Optional[date] = None
    billing_day: Optional[int] = PydanticField(default=None, ge=1, le=28)
    contract_version: Optional[int] = None
    billing_account_ready: bool
    billing_contact_name: Optional[str] = None
    billing_contact_email: Optional[str] = None


class PlatformFinanceFactsAvailability(BaseModel):
    subscriptions: bool = True
    billing_accounts: bool = True
    invoices: bool = True
    payments: bool = True
    delinquency: bool = True


class PlatformFinanceOverview(BaseModel):
    contracted_mrr: Decimal
    gross_mrr: Decimal
    discount_mrr: Decimal
    active_subscriptions: int
    trial_subscriptions: int
    pending_subscriptions: int
    billing_accounts_ready: int
    billing_accounts_total: int
    invoiced_total: Decimal
    received_total: Decimal
    refunded_total: Decimal
    open_invoice_balance: Decimal
    overdue_invoice_balance: Decimal
    draft_invoices: int
    open_invoices: int
    partially_paid_invoices: int
    paid_invoices: int
    overdue_invoices: int
    void_invoices: int
    facts: PlatformFinanceFactsAvailability
    subscriptions: List[PlatformFinanceSubscription]


class SaasBillingAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str = PydanticField(min_length=2, max_length=200)
    tax_id: str = PydanticField(min_length=11, max_length=18)
    contact_name: str = PydanticField(min_length=2, max_length=160)
    contact_email: str = PydanticField(min_length=5, max_length=254)
    contact_phone: Optional[str] = PydanticField(default=None, max_length=32)
    currency: str = PydanticField(default="BRL", pattern=r"^BRL$")
    expected_version: int = PydanticField(ge=0)
    reason: str = PydanticField(min_length=4, max_length=500)


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
    required: bool = False
    addon: bool = False
    recommended: bool = False


class TenantCapabilityUpdate(BaseModel):
    enabled: bool
    contract_limits: dict[str, Any] = PydanticField(default_factory=dict)
    reason: str = PydanticField(min_length=4, max_length=500)


class PlatformTenantProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = PydanticField(min_length=2, max_length=160)
    tenant_type: TenantTypeEnum
    lifecycle_phase: TenantPhaseEnum
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
    storage_limit_mb: Optional[int] = PydanticField(default=None, ge=128)
    capability_keys: List[str] = PydanticField(default_factory=list)
    activity_keys: List[str] = PydanticField(min_length=1)
    monthly_price: Decimal = PydanticField(default=Decimal("0.00"), ge=0)
    reason: str = PydanticField(default="Cadastro comercial inicial.", min_length=4, max_length=500)


class ServicePlanUpdate(ServicePlanCreate):
    is_active: bool = True


class TenantSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: Optional[uuid.UUID] = None
    status: SubscriptionStatusEnum
    monthly_amount: Optional[Decimal] = PydanticField(default=None, ge=0)
    billing_day: Optional[int] = PydanticField(default=None, ge=1, le=28)
    expected_version: Optional[int] = PydanticField(default=None, ge=1)


class OwnerTenantContractUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    niches: List[BusinessNiche] = PydanticField(min_length=1)
    capability_keys: List[str] = PydanticField(default_factory=list)
    capability_selection_mode: CapabilitySelectionMode
    quotas: OwnerQuotaCreate
    billing: OwnerBillingCreate
    subscription_status: SubscriptionStatusEnum
    expected_contract_version: int = PydanticField(ge=0)
    expected_billing_account_version: int = PydanticField(ge=0)
    reason: str = PydanticField(min_length=4, max_length=500)


class CommercialOfferProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    activity_keys: List[str] = PydanticField(min_length=1)
    addon_keys: List[str] = PydanticField(default_factory=list)


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


class PlatformTenantAdministratorReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_membership_id: Optional[uuid.UUID] = None
    email: str = PydanticField(min_length=5, max_length=254)
    full_name: str = PydanticField(min_length=2, max_length=160)
    reason: str = PydanticField(min_length=4, max_length=500)


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
    for store in stores:
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
        HealthComponent(
            key="api",
            label="Backend API",
            status="HEALTHY",
            details={"version": settings.VERSION, "evidence": "authenticated_request_served"},
        ),
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

    pending_states = {OutboxStatusEnum.PENDING, OutboxStatusEnum.PROCESSING}
    pending = _count(session, OutboxEvent, OutboxEvent.status.in_(pending_states))
    failed = _count(session, OutboxEvent, OutboxEvent.status == OutboxStatusEnum.FAILED)
    oldest_pending_at = session.exec(
        select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status.in_(pending_states))
    ).one()
    pending_age = (checked_at - oldest_pending_at).total_seconds() if oldest_pending_at else None
    outbox_status = "DEGRADED" if failed or (pending_age is not None and pending_age > 60) else "HEALTHY"
    components.append(HealthComponent(
        key="outbox", label="Fila transacional", status=outbox_status,
        details={
            "pending": pending,
            "failed": failed,
            "oldest_pending_at": oldest_pending_at.isoformat() if oldest_pending_at else None,
            "oldest_pending_age_seconds": round(pending_age, 1) if pending_age is not None else None,
            "degraded_after_seconds": 60,
        },
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
        totals=PlatformHealthTotals(
            tenants=_count(session, Tenant),
            pending_outbox=pending,
            failed_outbox=failed,
        ),
    )


@router.get("/platform/finance/overview", response_model=PlatformFinanceOverview)
def platform_finance_overview(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Contractual SaaS revenue projection; never reads tenant sales or cash data."""
    require_platform_permission(session, principal, FINANCE_READ)
    subscriptions = list(session.exec(select(TenantSubscription)).all())
    tenants = {item.id: item for item in session.exec(select(Tenant)).all()}
    plans = {item.id: item for item in session.exec(select(ServicePlan)).all()}
    accounts = {
        item.tenant_id: item for item in session.exec(select(SaasBillingAccount)).all()
    }
    invoices = list(session.exec(select(SaasInvoice)).all())
    allocations = list(session.exec(select(SaasPaymentAllocation)).all())
    refunds = list(session.exec(select(SaasRefund)).all())
    contracts = {}
    for contract in session.exec(
        select(TenantContract).order_by(TenantContract.tenant_id, TenantContract.version.desc())
    ).all():
        contracts.setdefault(contract.tenant_id, contract)

    amounts = {
        item.tenant_id: commercial_pricing.subscription_amounts(item, effective_on=date.today())
        for item in subscriptions
    }
    rows = [
        PlatformFinanceSubscription(
            tenant_id=item.tenant_id,
            tenant_name=tenants[item.tenant_id].name if item.tenant_id in tenants else "Tenant removido",
            plan_name=plans[item.plan_id].name if item.plan_id in plans else None,
            subscription_status=item.status,
            monthly_amount=amounts[item.tenant_id][2],
            gross_monthly_amount=amounts[item.tenant_id][0],
            discount_amount=amounts[item.tenant_id][1],
            discount_reason_code=item.discount_reason_code,
            discount_ends_on=item.discount_ends_on,
            billing_day=item.billing_day,
            contract_version=contracts[item.tenant_id].version if item.tenant_id in contracts else None,
            billing_account_ready=_billing_account_ready(accounts.get(item.tenant_id)),
            billing_contact_name=(accounts[item.tenant_id].contact_name if item.tenant_id in accounts else None),
            billing_contact_email=(accounts[item.tenant_id].contact_email if item.tenant_id in accounts else None),
        )
        for item in subscriptions
    ]
    rows.sort(key=lambda item: (item.billing_account_ready, item.tenant_name.lower()))
    return PlatformFinanceOverview(
        contracted_mrr=sum(
            (amounts[item.tenant_id][2] for item in subscriptions if item.status == SubscriptionStatusEnum.ACTIVE),
            Decimal("0.00"),
        ),
        gross_mrr=sum(
            (amounts[item.tenant_id][0] for item in subscriptions if item.status == SubscriptionStatusEnum.ACTIVE),
            Decimal("0.00"),
        ),
        discount_mrr=sum(
            (amounts[item.tenant_id][1] for item in subscriptions if item.status == SubscriptionStatusEnum.ACTIVE),
            Decimal("0.00"),
        ),
        active_subscriptions=sum(item.status == SubscriptionStatusEnum.ACTIVE for item in subscriptions),
        trial_subscriptions=sum(item.status == SubscriptionStatusEnum.TRIAL for item in subscriptions),
        pending_subscriptions=sum(item.status == SubscriptionStatusEnum.PENDING for item in subscriptions),
        billing_accounts_ready=sum(_billing_account_ready(item) for item in accounts.values()),
        billing_accounts_total=len(accounts),
        invoiced_total=sum(
            (
                item.total_amount for item in invoices
                if item.status not in {SaasInvoiceStatusEnum.DRAFT, SaasInvoiceStatusEnum.VOID}
            ),
            Decimal("0.00"),
        ),
        received_total=(
            sum((item.amount for item in allocations), Decimal("0.00"))
            - sum((item.amount for item in refunds), Decimal("0.00"))
        ),
        refunded_total=sum((item.amount for item in refunds), Decimal("0.00")),
        open_invoice_balance=sum(
            (
                item.balance_amount for item in invoices
                if item.status in {
                    SaasInvoiceStatusEnum.OPEN,
                    SaasInvoiceStatusEnum.PARTIALLY_PAID,
                    SaasInvoiceStatusEnum.OVERDUE,
                }
            ),
            Decimal("0.00"),
        ),
        overdue_invoice_balance=sum(
            (item.balance_amount for item in invoices if item.status == SaasInvoiceStatusEnum.OVERDUE),
            Decimal("0.00"),
        ),
        draft_invoices=sum(item.status == SaasInvoiceStatusEnum.DRAFT for item in invoices),
        open_invoices=sum(item.status == SaasInvoiceStatusEnum.OPEN for item in invoices),
        partially_paid_invoices=sum(
            item.status == SaasInvoiceStatusEnum.PARTIALLY_PAID for item in invoices
        ),
        paid_invoices=sum(item.status == SaasInvoiceStatusEnum.PAID for item in invoices),
        overdue_invoices=sum(item.status == SaasInvoiceStatusEnum.OVERDUE for item in invoices),
        void_invoices=sum(item.status == SaasInvoiceStatusEnum.VOID for item in invoices),
        facts=PlatformFinanceFactsAvailability(),
        subscriptions=rows,
    )


@router.put(
    "/platform/finance/billing-accounts/{tenant_id}",
    response_model=SaasBillingAccount,
)
def update_saas_billing_account(
    tenant_id: uuid.UUID,
    data: SaasBillingAccountUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    """Versioned platform billing master; never reads tenant operations."""
    actor = require_platform_permission(
        session, principal, FINANCE_MANAGE_BILLING, require_aal2=True
    )
    assert actor is not None
    if session.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    normalized_tax_id = _normalize_tax_id(data.tax_id)
    email = data.contact_email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="Informe um e-mail de cobrança válido.")
    values = {
        "legal_name": data.legal_name.strip(),
        "tax_id": normalized_tax_id,
        "contact_name": data.contact_name.strip(),
        "contact_email": email,
        "contact_phone": data.contact_phone.strip() if data.contact_phone else None,
        "currency": data.currency,
        "updated_at": datetime.utcnow(),
    }
    account = session.exec(
        select(SaasBillingAccount).where(SaasBillingAccount.tenant_id == tenant_id)
    ).first()
    previous_version = account.version if account else 0
    previous = {
        "version": previous_version,
        "legal_name": account.legal_name if account else None,
        "tax_id_suffix": account.tax_id[-4:] if account and account.tax_id else None,
        "contact_name": account.contact_name if account else None,
        "contact_email": account.contact_email if account else None,
        "contact_phone": account.contact_phone if account else None,
        "currency": account.currency if account else None,
    }

    if account is None:
        if data.expected_version != 0:
            raise HTTPException(
                status_code=409,
                detail="A conta de cobrança foi alterada por outra sessão. Recarregue os dados antes de salvar.",
            )
        account = SaasBillingAccount(tenant_id=tenant_id, version=1, **values)
        session.add(account)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="A conta de cobrança foi criada por outra sessão. Recarregue os dados antes de salvar.",
            ) from exc
    else:
        result = session.exec(
            sa_update(SaasBillingAccount)
            .where(
                SaasBillingAccount.id == account.id,
                SaasBillingAccount.version == data.expected_version,
            )
            .values(**values, version=data.expected_version + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="A conta de cobrança foi alterada por outra sessão. Recarregue os dados antes de salvar.",
            )
        session.expire(account)
        session.refresh(account)

    payload = {
        "tenant_id": str(tenant_id),
        "billing_account_id": str(account.id),
        "previous": previous,
        "current": {
            "version": account.version,
            "legal_name": account.legal_name,
            "tax_id_suffix": account.tax_id[-4:] if account.tax_id else None,
            "contact_name": account.contact_name,
            "contact_email": account.contact_email,
            "contact_phone": account.contact_phone,
            "currency": account.currency,
        },
        "reason": data.reason.strip(),
    }
    audit, _ = reliability_service.write_audit_and_outbox(
        session,
        tenant_id=tenant_id,
        store_id=None,
        actor_id=actor.id,
        action="platform.finance.billing_account_updated",
        target=f"saas_billing_account:{account.id}",
        audit_payload=payload,
        aggregate_type="saas_billing_account",
        aggregate_id=str(account.id),
        event_type="platform.finance.billing_account_updated",
        outbox_payload=payload,
    )
    audit.platform_scope = True
    session.add(audit)
    session.commit()
    session.refresh(account)
    return account


def _activity_catalog(session: Session) -> list[OwnerNicheRead]:
    activities = session.exec(
        select(CommercialActivity)
        .where(CommercialActivity.status == "ACTIVE")
        .order_by(CommercialActivity.name)
    ).all()
    rules = session.exec(select(CommercialActivityCapability)).all()
    by_activity: dict[str, list[CommercialActivityCapability]] = {}
    for rule in rules:
        by_activity.setdefault(rule.activity_key, []).append(rule)
    return [
        OwnerNicheRead(
            key=activity.key,
            name=activity.name,
            description=activity.description,
            required_capabilities=[
                capability_payload(rule.capability_key)
                for rule in by_activity.get(activity.key, [])
                if rule.role == "REQUIRED"
            ],
            allowed_addons=[
                capability_payload(rule.capability_key)
                for rule in by_activity.get(activity.key, [])
                if rule.role == "OPTIONAL"
            ],
        )
        for activity in activities
    ]


@router.get("/platform/activities", response_model=List[OwnerNicheRead])
@router.get("/platform/niches", response_model=List[OwnerNicheRead], deprecated=True)
def list_owner_activities(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return _activity_catalog(session)


def _validated_activity_keys(session: Session, keys: List[str]) -> list[str]:
    normalized = list(dict.fromkeys(key.strip().upper() for key in keys if key.strip()))
    rows = session.exec(
        select(CommercialActivity).where(
            CommercialActivity.key.in_(normalized),
            CommercialActivity.status == "ACTIVE",
        )
    ).all()
    existing = {row.key for row in rows}
    missing = set(normalized).difference(existing)
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Atividades comerciais inexistentes ou inativas: " + ", ".join(sorted(missing)),
        )
    if not normalized:
        raise HTTPException(status_code=422, detail="Selecione ao menos uma atividade comercial.")
    return normalized


@router.post("/platform/commercial-offers/resolve", response_model=dict[str, Any])
def resolve_commercial_offer(
    data: CommercialOfferProposalCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    plan = session.get(ServicePlan, data.plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=422, detail="Selecione um plano ativo.")
    activity_keys = _validated_activity_keys(session, data.activity_keys)
    rows = session.exec(
        select(CommercialActivityCapability).where(
            CommercialActivityCapability.activity_key.in_(activity_keys)
        )
    ).all()
    try:
        proposal = compose_commercial_offer(
            plan_capability_keys=plan.capability_keys,
            plan_activity_keys=plan.activity_keys,
            selected_activity_keys=activity_keys,
            requested_addon_keys=data.addon_keys,
            rules=[
                ActivityRule(
                    activity_key=row.activity_key,
                    capability_key=row.capability_key,
                    role=row.role,
                    default_selected=row.default_selected,
                )
                for row in rows
            ],
        )
    except CommercialOfferError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "plan_id": str(plan.id),
        "plan_version": plan.version,
        "plan_name": plan.name,
        **proposal,
    }


def _contract_offer(
    session: Session,
    *,
    plan: ServicePlan,
    activity_keys: list[str],
    capability_keys: list[str],
    selection_mode: CapabilitySelectionMode,
) -> dict[str, Any]:
    normalized_activities = _validated_activity_keys(session, activity_keys)
    rows = session.exec(
        select(CommercialActivityCapability).where(
            CommercialActivityCapability.activity_key.in_(normalized_activities)
        )
    ).all()
    rules = [
        ActivityRule(
            activity_key=row.activity_key,
            capability_key=row.capability_key,
            role=row.role,
            default_selected=row.default_selected,
        )
        for row in rows
    ]
    try:
        base = compose_commercial_offer(
            plan_capability_keys=plan.capability_keys,
            plan_activity_keys=plan.activity_keys,
            selected_activity_keys=normalized_activities,
            rules=rules,
        )
        if base["gaps"]:
            missing = ", ".join(item["key"] for item in base["gaps"])
            raise CommercialOfferError(
                "O plano não cobre capabilities obrigatórias das atividades: " + missing
            )
        if selection_mode == CapabilitySelectionMode.OFFER_DEFAULT:
            if capability_keys:
                raise CommercialOfferError(
                    "O modo OFFER_DEFAULT não aceita uma seleção manual de capabilities."
                )
            return base

        explicit = set(selected_entitlement_keys(capability_keys))
        required = set(base["capability_keys"])
        missing_required = required.difference(explicit)
        if missing_required:
            raise CommercialOfferError(
                "Capabilities obrigatórias ausentes: " + ", ".join(sorted(missing_required))
            )
        optional = {
            row.capability_key for row in rows if row.role == "OPTIONAL"
        }
        addon_keys = explicit.difference(required)
        invalid = addon_keys.difference(optional)
        if invalid:
            raise CommercialOfferError(
                "Capabilities fora da matriz contratual: " + ", ".join(sorted(invalid))
            )
        proposal = compose_commercial_offer(
            plan_capability_keys=plan.capability_keys,
            plan_activity_keys=plan.activity_keys,
            selected_activity_keys=normalized_activities,
            requested_addon_keys=sorted(addon_keys),
            rules=rules,
        )
        if set(proposal["capability_keys"]) != explicit:
            raise CommercialOfferError(
                "A seleção explícita não corresponde à proposta resolvida com suas dependências."
            )
        return proposal
    except (CommercialOfferError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/platform/capabilities", response_model=List[dict[str, Any]])
def list_owner_capabilities(
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    return [
        capability_payload(key)
        for key in CAPABILITY_REGISTRY
        if key in IMPLEMENTED_CAPABILITIES
    ]


def _validate_quota(label: str, requested: int, maximum: Optional[int]) -> None:
    if maximum is not None and requested > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"A quota de {label} ({requested}) excede o limite do plano ({maximum}).",
        )


def _billing_account_ready(account: Optional[SaasBillingAccount]) -> bool:
    return bool(
        account
        and account.legal_name
        and account.tax_id
        and account.contact_name
        and account.contact_email
    )


def _upsert_saas_billing_account(
    session: Session,
    *,
    tenant: Tenant,
    profile: Optional[TenantProfile],
    billing: OwnerBillingCreate,
    expected_version: Optional[int] = None,
) -> SaasBillingAccount:
    account = session.exec(
        select(SaasBillingAccount).where(SaasBillingAccount.tenant_id == tenant.id)
    ).first()
    if account is None:
        if expected_version not in {None, 0}:
            raise HTTPException(
                status_code=409,
                detail="A conta de cobrança foi alterada por outra sessão. Recarregue os dados antes de salvar.",
            )
        account = SaasBillingAccount(tenant_id=tenant.id)
    else:
        if expected_version is not None:
            result = session.exec(
                sa_update(SaasBillingAccount)
                .where(
                    SaasBillingAccount.id == account.id,
                    SaasBillingAccount.version == expected_version,
                )
                .values(
                    legal_name=(profile.legal_name if profile and profile.legal_name else tenant.legal_name),
                    tax_id=profile.tax_id if profile else None,
                    contact_name=billing.contact_name.strip(),
                    contact_email=billing.email.strip().lower(),
                    contact_phone=billing.phone.strip() if billing.phone else None,
                    currency="BRL",
                    version=expected_version + 1,
                    updated_at=datetime.utcnow(),
                )
            )
            if result.rowcount != 1:
                session.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="A conta de cobrança foi alterada por outra sessão. Recarregue os dados antes de salvar.",
                )
            session.expire(account)
            session.refresh(account)
            return account
        account.version += 1
    account.legal_name = profile.legal_name if profile and profile.legal_name else tenant.legal_name
    account.tax_id = profile.tax_id if profile else None
    account.contact_name = billing.contact_name.strip()
    account.contact_email = billing.email.strip().lower()
    account.contact_phone = billing.phone.strip() if billing.phone else None
    account.currency = "BRL"
    account.updated_at = datetime.utcnow()
    session.add(account)
    return account


@router.post("/platform/tenants", response_model=PlatformTenantProvisioned, status_code=201)
def provision_owner_tenant(
    data: OwnerTenantProvisionCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    plan = session.get(ServicePlan, data.plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=422, detail="Selecione um plano ativo.")
    _validate_quota("usuários", data.quotas.users, plan.user_limit)
    _validate_quota("dispositivos", data.quotas.devices, plan.terminal_limit)
    _validate_quota("unidades", data.quotas.units, plan.store_limit)
    _validate_quota("storage", data.quotas.storage_mb, plan.storage_limit_mb)
    selected_niches = list(dict.fromkeys(data.niches))
    proposal = _contract_offer(
        session,
        plan=plan,
        activity_keys=[niche.value for niche in selected_niches],
        capability_keys=data.capability_keys,
        selection_mode=data.capability_selection_mode,
    )
    selected_keys = tuple(proposal["capability_keys"])

    tax_id = _normalize_tax_id(data.tax_id)
    if session.exec(select(Tenant).where(Tenant.slug == data.slug)).first():
        raise HTTPException(status_code=409, detail="Este identificador de cliente já está em uso.")
    if session.exec(select(TenantProfile).where(TenantProfile.tax_id == tax_id)).first():
        raise HTTPException(status_code=409, detail="Este CPF ou CNPJ já pertence a outro cliente.")
    email = data.initial_admin.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Informe um e-mail válido para o administrador inicial.")
    existing_user = session.exec(select(User).where(User.email == email)).first()
    provider_subject = None
    delivery_status = "IDENTIDADE_EXISTENTE"

    tenant, store = identity_service.provision_tenant(
        session,
        name=data.name.strip(), slug=data.slug,
        first_store_name=data.first_store_name.strip(),
        first_store_code=data.first_store_code.strip().upper(),
        actor_id=actor.id, customer_type=_legacy_customer_type(data.tenant_type, data.lifecycle_phase),
        legal_name=data.legal_name.strip(), tax_id=tax_id,
        state_registration=data.state_registration.strip() if data.state_registration else None,
        municipal_registration=data.municipal_registration.strip() if data.municipal_registration else None,
        industry=", ".join(niche.value for niche in selected_niches) or None,
        company_email=data.company_email.strip().lower() if data.company_email else None,
        company_phone=data.company_phone.strip(), website=data.website.strip() if data.website else None,
        contact_name=data.contact_name.strip(),
        contact_job_title=data.contact_job_title.strip() if data.contact_job_title else None,
        contact_email=data.contact_email.strip().lower(),
        contact_phone=data.contact_phone.strip() if data.contact_phone else None,
        postal_code=_digits(data.postal_code), street=data.street.strip(),
        street_number=data.street_number.strip(),
        address_complement=data.address_complement.strip() if data.address_complement else None,
        district=data.district.strip(), city=data.city.strip(), state=data.state.strip().upper(),
        plan_id=data.plan_id, commit=False,
    )
    if existing_user is None:
        invited = supabase_admin.invite_user(
            email=email,
            full_name=data.initial_admin.full_name.strip(),
            tenant_id=str(tenant.id),
        )
        provider_subject = str(invited["id"])
        delivery_status = "ENVIADO"
    subscription = session.get(TenantSubscription, tenant.id)
    assert subscription is not None
    profile = session.get(TenantProfile, tenant.id)
    assert profile is not None
    profile.tenant_type = data.tenant_type
    profile.lifecycle_phase = data.lifecycle_phase
    session.add(profile)
    subscription.status = (
        SubscriptionStatusEnum.TRIAL
        if data.lifecycle_phase in {TenantPhaseEnum.TEST, TenantPhaseEnum.PILOT}
        else SubscriptionStatusEnum.ACTIVE
    )
    _commercial_terms(subscription, data.billing)
    subscription.billing_day = data.billing.billing_day
    subscription.contracted_user_limit = data.quotas.users
    subscription.contracted_device_limit = data.quotas.devices
    subscription.contracted_store_limit = data.quotas.units
    session.add(subscription)

    for key in selected_keys:
        _ensure_capability_definition(session, key)
    session.flush()
    for key in selected_keys:
        session.add(TenantCapability(
            tenant_id=tenant.id,
            key=key,
            enabled=True,
            status=EntitlementStatusEnum.ACTIVE,
        ))

    limits = {
        "users": data.quotas.users,
        "devices": data.quotas.devices,
        "units": data.quotas.units,
        "storage_mb": data.quotas.storage_mb,
        "niche": selected_niches[0].value if selected_niches else None,
        "business_niches": [niche.value for niche in selected_niches],
        "billing": _billing_contract_snapshot(data.billing, subscription),
    }
    plan_revision = _current_plan_revision(session, plan)
    entitlement_snapshot = build_entitlement_snapshot(
        proposal=proposal,
        users=data.quotas.users,
        devices=data.quotas.devices,
        units=data.quotas.units,
        storage_mb=data.quotas.storage_mb,
    )
    contract = TenantContract(
        tenant_id=tenant.id, version=1, status="ACTIVE", plan_id=plan.id,
        plan_revision_id=plan_revision.id,
        limits=limits, starts_at=datetime.utcnow(),
        reason="Provisionamento comercial completo pelo Owner.", created_by=actor.id,
        **entitlement_snapshot,
    )
    session.add(contract)
    _upsert_saas_billing_account(
        session, tenant=tenant, profile=profile, billing=data.billing,
    )
    membership = identity_service.provision_tenant_access(
        session, tenant=tenant, email=email, full_name=data.initial_admin.full_name,
        role=RoleEnum.TENANT_OWNER, store_id=None, actor_id=actor.id,
        provider_subject=provider_subject, commit=False,
    )
    session.flush()
    admin_user = session.get(User, membership.user_id)
    assert admin_user is not None
    local, domain = email.split("@", 1)
    session.add(IdentityDeliveryEvent(
        tenant_id=tenant.id, membership_id=membership.id, kind="CONTRACT_ADMIN_INVITE",
        recipient_masked=f"{local[:2]}{'*' * max(1, len(local) - 2)}@{domain}",
        provider="SUPABASE_SMTP", status=delivery_status,
        sanitized_detail="Primeiro acesso administrativo entregue durante o provisionamento OWNER-P0.",
    ))
    payload = {
        "tenant_id": str(tenant.id), "niches": [niche.value for niche in selected_niches],
        "plan_id": str(plan.id), "limits": limits,
        "capability_keys": list(selected_keys),
        "capability_entitlements": entitlement_snapshot["capability_entitlements"],
        "initial_admin_id": str(admin_user.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant.id, store_id=None, actor_id=actor.id,
        action="platform.tenant.owner_p0_provisioned", target=f"tenant:{tenant.id}",
        audit_payload=payload, aggregate_type="tenant_contract", aggregate_id=str(contract.id),
        event_type="platform.tenant.owner_p0_provisioned", outbox_payload=payload,
    )
    session.commit()
    session.refresh(tenant); session.refresh(store); session.refresh(contract); session.refresh(membership)
    return PlatformTenantProvisioned(
        tenant=tenant, first_store=store, niche=selected_niches[0] if selected_niches else None, niches=selected_niches, contract=contract,
        initial_admin=_tenant_access_read(membership, admin_user, None),
        delivery_status=delivery_status,
    )


# Lower-level primitive retained for migration/tests. It is intentionally not
# exposed as an HTTP route; the public Owner route above never creates an
# incomplete commercial tenant.
def provision_platform_tenant(
    data: PlatformTenantCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    user = require_platform_role(
        session, principal, PLATFORM_MANAGERS, require_aal2=True
    )
    assert user is not None
    tax_id = _normalize_tax_id(data.tax_id)
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
    capabilities = session.exec(
        select(TenantCapability).where(TenantCapability.tenant_id == tenant_id).order_by(TenantCapability.key)
    ).all()
    contract = session.exec(
        select(TenantContract).where(TenantContract.tenant_id == tenant_id).order_by(TenantContract.version.desc())
    ).first()
    effective_plan_id = (
        subscription.plan_id if subscription and subscription.plan_id
        else contract.plan_id if contract and contract.plan_id
        else None
    )
    plan = session.get(ServicePlan, effective_plan_id) if effective_plan_id else None
    billing_account = session.exec(
        select(SaasBillingAccount).where(SaasBillingAccount.tenant_id == tenant_id)
    ).first()
    assignment_row = session.exec(
        select(TenantProfileAssignment, CapabilityProfileRevision)
        .join(CapabilityProfileRevision, CapabilityProfileRevision.id == TenantProfileAssignment.revision_id)
        .where(TenantProfileAssignment.tenant_id == tenant_id, TenantProfileAssignment.status == "ACTIVE")
    ).first()
    niche = None
    if assignment_row and assignment_row[1].profile_key in {item.value for item in BusinessNiche}:
        niche = BusinessNiche(assignment_row[1].profile_key)
    niche_values = contract.limits.get("business_niches", []) if contract else []
    if not niche_values and contract and contract.limits.get("niche"):
        niche_values = [contract.limits["niche"]]
    niches = [BusinessNiche(value) for value in niche_values if value in {item.value for item in BusinessNiche}]
    if not niches and niche:
        niches = [niche]
    if not niches and profile and profile.industry:
        known_niches = {item.value for item in BusinessNiche}
        legacy_values = [
            value.strip().upper().replace(" ", "_")
            for value in profile.industry.split(",")
        ]
        niches = [BusinessNiche(value) for value in legacy_values if value in known_niches]
    if niches:
        niche = niches[0]
    store_map = {store.id: store for store in stores}
    rows = session.exec(
        select(Membership, User).join(User, User.id == Membership.user_id).where(
            Membership.tenant_id == tenant_id,
            Membership.role.in_([RoleEnum.TENANT_OWNER, RoleEnum.OWNER, RoleEnum.ADMIN]),
        )
    ).all()
    return PlatformTenantDetail(
        tenant=_tenant_read(
            tenant, profile=profile, contacts=list(contacts), stores=list(stores),
        ),
        profile=profile,
        contacts=list(contacts),
        subscription=subscription,
        plan=plan,
        stores=stores,
        accesses=[_tenant_access_read(membership, user, store_map.get(membership.store_id)) for membership, user in rows],
        capabilities=list(capabilities),
        niche=niche,
        niches=niches,
        contract=contract,
        billing_account=billing_account,
        resource_usage=tenant_count_quota_read_model(session, tenant_id),
        storage_usage=storage_quota_read_model(session, tenant_id),
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
        customer_type=_legacy_customer_type(data.tenant_type, data.lifecycle_phase),
        tenant_type=data.tenant_type,
        lifecycle_phase=data.lifecycle_phase,
        trade_name=data.name.strip(),
    )
    normalized_tax_id = _normalize_tax_id(data.tax_id)
    if normalized_tax_id:
        duplicate = session.exec(select(TenantProfile).where(
            TenantProfile.tax_id == normalized_tax_id,
            TenantProfile.tenant_id != tenant_id,
        )).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Este CPF ou CNPJ já pertence a outro cliente.")
    previous_type = getattr(profile.tenant_type, "value", str(profile.tenant_type))
    tenant.name = data.name.strip()
    tenant.legal_name = data.legal_name.strip() if data.legal_name else None
    tenant.updated_at = datetime.utcnow()
    profile.customer_type = _legacy_customer_type(data.tenant_type, data.lifecycle_phase)
    profile.tenant_type = data.tenant_type
    profile.lifecycle_phase = data.lifecycle_phase
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
        "tenant_type_from": previous_type,
        "tenant_type_to": data.tenant_type.value,
        "lifecycle_phase_to": data.lifecycle_phase.value,
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
    try:
        capability_keys = list(selected_entitlement_keys(data.capability_keys))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if session.exec(select(ServicePlan).where(ServicePlan.code == code)).first():
        raise HTTPException(status_code=409, detail="Já existe um plano com este código.")
    activity_keys = _validated_activity_keys(session, data.activity_keys)
    plan = ServicePlan(
        code=code, name=data.name.strip(), description=data.description,
        store_limit=data.store_limit, user_limit=data.user_limit,
        terminal_limit=data.terminal_limit, storage_limit_mb=data.storage_limit_mb,
        capability_keys=capability_keys, activity_keys=activity_keys,
        monthly_price=data.monthly_price, version=1,
    )
    session.add(plan)
    session.flush()
    revision = _snapshot_plan(session, plan=plan, actor_id=actor.id, reason=data.reason)
    session.add(AuditEvent(
        actor_id=actor.id, tenant_id=None, store_id=None, platform_scope=True,
        action="platform.plan.created", target=f"service_plan:{plan.id}",
        payload=json.dumps({
            "plan_id": str(plan.id), "code": plan.code,
            "version": plan.version, "revision_id": str(revision.id),
            "capability_keys": capability_keys, "activity_keys": activity_keys,
        }),
    ))
    session.commit()
    session.refresh(plan)
    return plan


@router.put("/platform/plans/{plan_id}", response_model=ServicePlan)
def update_service_plan(
    plan_id: uuid.UUID,
    data: ServicePlanUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    plan = session.get(ServicePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plano comercial não encontrado.")
    code = data.code.strip().upper()
    duplicate = session.exec(select(ServicePlan).where(ServicePlan.code == code, ServicePlan.id != plan_id)).first()
    try:
        capability_keys = list(selected_entitlement_keys(data.capability_keys))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if duplicate:
        raise HTTPException(status_code=409, detail="Já existe outro plano com este código.")
    activity_keys = _validated_activity_keys(session, data.activity_keys)
    previous = {
        "code": plan.code, "name": plan.name, "is_active": plan.is_active,
        "store_limit": plan.store_limit, "user_limit": plan.user_limit,
        "terminal_limit": plan.terminal_limit, "storage_limit_mb": plan.storage_limit_mb,
        "monthly_price": str(plan.monthly_price),
        "version": plan.version, "capability_keys": list(plan.capability_keys),
        "activity_keys": list(plan.activity_keys),
    }
    plan.code = code
    plan.name = data.name.strip()
    plan.description = data.description.strip() if data.description else None
    plan.store_limit = data.store_limit
    plan.user_limit = data.user_limit
    plan.terminal_limit = data.terminal_limit
    plan.storage_limit_mb = data.storage_limit_mb
    plan.capability_keys = capability_keys
    plan.activity_keys = activity_keys
    plan.monthly_price = data.monthly_price
    plan.is_active = data.is_active
    plan.version += 1
    plan.updated_at = datetime.utcnow()
    session.add(plan)
    session.flush()
    revision = _snapshot_plan(session, plan=plan, actor_id=actor.id, reason=data.reason)
    session.add(AuditEvent(
        actor_id=actor.id, tenant_id=None, store_id=None, platform_scope=True,
        action="platform.plan.updated", target=f"service_plan:{plan.id}",
        payload=json.dumps({
            "plan_id": str(plan.id), "previous": previous,
            "current": {
                "code": plan.code, "name": plan.name, "is_active": plan.is_active,
                "store_limit": plan.store_limit, "user_limit": plan.user_limit,
                "terminal_limit": plan.terminal_limit, "storage_limit_mb": plan.storage_limit_mb,
                "monthly_price": str(plan.monthly_price),
                "version": plan.version, "revision_id": str(revision.id),
                "capability_keys": capability_keys, "activity_keys": activity_keys,
            },
        }),
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
    if data.expected_version is not None and subscription.version != data.expected_version:
        raise HTTPException(
            status_code=409,
            detail="A assinatura foi alterada por outra sessão. Recarregue os dados antes de salvar.",
        )
    subscription.plan_id = data.plan_id
    subscription.status = data.status
    if data.monthly_amount is not None:
        subscription.monthly_amount = data.monthly_amount
        subscription.gross_monthly_amount = data.monthly_amount
        subscription.discount_type = None
        subscription.discount_value = Decimal("0.0000")
        subscription.discount_amount = Decimal("0.00")
        subscription.discount_reason_code = None
        subscription.discount_reason = None
        subscription.discount_starts_on = None
        subscription.discount_ends_on = None
        subscription.discount_review_on = None
    if data.billing_day is not None:
        subscription.billing_day = data.billing_day
    subscription.version += 1
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


@router.put("/platform/tenants/{tenant_id}/contract", response_model=PlatformTenantDetail)
def update_owner_tenant_contract(
    tenant_id: uuid.UUID,
    data: OwnerTenantContractUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_permission(
        session, principal, FINANCE_MANAGE_BILLING, require_aal2=True
    )
    assert actor is not None
    _apply_owner_tenant_contract(session, tenant_id, data, actor)
    session.commit()
    return platform_tenant_detail(tenant_id, principal, session)


def _apply_owner_tenant_contract(
    session: Session,
    tenant_id: uuid.UUID,
    data: OwnerTenantContractUpdate,
    actor: User,
) -> TenantContract:
    """Apply a contract version without committing the surrounding transaction."""
    tenant = session.exec(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update()
    ).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    plan = session.get(ServicePlan, data.plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=422, detail="Selecione um plano ativo.")
    previous_contract = session.exec(select(TenantContract).where(
        TenantContract.tenant_id == tenant_id,
    ).order_by(TenantContract.version.desc())).first()
    current_contract_version = previous_contract.version if previous_contract else 0
    if data.expected_contract_version != current_contract_version:
        raise HTTPException(
            status_code=409,
            detail="O contrato foi alterado por outra sessão. Recarregue os dados antes de salvar.",
        )
    _validate_quota("usuários", data.quotas.users, plan.user_limit)
    _validate_quota("dispositivos", data.quotas.devices, plan.terminal_limit)
    _validate_quota("unidades", data.quotas.units, plan.store_limit)
    _validate_quota("storage", data.quotas.storage_mb, plan.storage_limit_mb)
    selected_niches = list(dict.fromkeys(data.niches))
    proposal = _contract_offer(
        session,
        plan=plan,
        activity_keys=[niche.value for niche in selected_niches],
        capability_keys=data.capability_keys,
        selection_mode=data.capability_selection_mode,
    )
    selected_keys = tuple(proposal["capability_keys"])

    current = {
        item.key: item for item in session.exec(
            select(TenantCapability).where(TenantCapability.tenant_id == tenant_id)
        ).all()
    }
    for key in selected_keys:
        _ensure_capability_definition(session, key)
    session.flush()
    for key, entitlement in current.items():
        if key not in selected_keys and entitlement.enabled:
            entitlement.enabled = False
            entitlement.status = EntitlementStatusEnum.SUSPENDED
            entitlement.updated_at = datetime.utcnow()
            session.add(entitlement)
    for key in selected_keys:
        entitlement = current.get(key) or TenantCapability(tenant_id=tenant_id, key=key)
        entitlement.enabled = True
        entitlement.status = EntitlementStatusEnum.ACTIVE
        entitlement.updated_at = datetime.utcnow()
        session.add(entitlement)

    profile = session.get(TenantProfile, tenant_id)
    if profile:
        profile.industry = ", ".join(niche.value for niche in selected_niches) or None
        profile.updated_at = datetime.utcnow()
        session.add(profile)
    subscription = session.get(TenantSubscription, tenant_id) or TenantSubscription(tenant_id=tenant_id)
    subscription.plan_id = plan.id
    subscription.status = data.subscription_status
    _commercial_terms(subscription, data.billing)
    subscription.billing_day = data.billing.billing_day
    subscription.contracted_user_limit = data.quotas.users
    subscription.contracted_device_limit = data.quotas.devices
    subscription.contracted_store_limit = data.quotas.units
    subscription.version += 1
    subscription.updated_at = datetime.utcnow()
    session.add(subscription)

    limits = {
        "users": data.quotas.users,
        "devices": data.quotas.devices,
        "units": data.quotas.units,
        "storage_mb": data.quotas.storage_mb,
        "niche": selected_niches[0].value if selected_niches else None,
        "business_niches": [niche.value for niche in selected_niches],
        "billing": _billing_contract_snapshot(data.billing, subscription),
    }
    plan_revision = _current_plan_revision(session, plan)
    entitlement_snapshot = build_entitlement_snapshot(
        proposal=proposal,
        users=data.quotas.users,
        devices=data.quotas.devices,
        units=data.quotas.units,
        storage_mb=data.quotas.storage_mb,
    )
    contract = TenantContract(
        tenant_id=tenant_id,
        version=(previous_contract.version + 1) if previous_contract else 1,
        status="ACTIVE", plan_id=plan.id, plan_revision_id=plan_revision.id, limits=limits,
        starts_at=datetime.utcnow(),
        reason=data.reason.strip(), created_by=actor.id,
        **entitlement_snapshot,
    )
    session.add(contract)
    _upsert_saas_billing_account(
        session, tenant=tenant, profile=profile, billing=data.billing,
        expected_version=data.expected_billing_account_version,
    )
    payload = {
        "tenant_id": str(tenant_id), "plan_id": str(plan.id),
        "niches": [niche.value for niche in selected_niches],
        "capability_keys": list(selected_keys),
        "capability_entitlements": entitlement_snapshot["capability_entitlements"],
        "limits": limits,
        "contract_version": contract.version, "actor_id": str(actor.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.tenant.contract_updated", target=f"tenant:{tenant_id}",
        audit_payload=payload, aggregate_type="tenant_contract", aggregate_id=str(contract.id),
        event_type="platform.tenant.contract_updated", outbox_payload=payload,
    )
    return contract


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


def _tenant_niches(session: Session, tenant_id: uuid.UUID) -> list[BusinessNiche]:
    contract = session.exec(
        select(TenantContract).where(TenantContract.tenant_id == tenant_id).order_by(TenantContract.version.desc())
    ).first()
    if contract:
        values = contract.activity_keys or contract.limits.get("business_niches", [])
        niches = [BusinessNiche(value) for value in values if value in {item.value for item in BusinessNiche}]
        if niches:
            return niches
    revision = session.exec(
        select(CapabilityProfileRevision)
        .join(TenantProfileAssignment, TenantProfileAssignment.revision_id == CapabilityProfileRevision.id)
        .where(TenantProfileAssignment.tenant_id == tenant_id, TenantProfileAssignment.status == "ACTIVE")
    ).first()
    if revision is None or revision.profile_key not in {item.value for item in BusinessNiche}:
        return []
    return [BusinessNiche(revision.profile_key)]


def _tenant_niche(session: Session, tenant_id: uuid.UUID) -> Optional[BusinessNiche]:
    niches = _tenant_niches(session, tenant_id)
    return niches[0] if niches else None


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
    snapshot = resolve_contract_entitlements(session, tenant_id)
    enabled_keys = (
        set(snapshot.capability_keys)
        if snapshot is not None
        else {key for key, item in entitlements.items() if item.enabled}
    )
    niches = _tenant_niches(session, tenant_id)
    activity_rules = session.exec(
        select(CommercialActivityCapability).where(
            CommercialActivityCapability.activity_key.in_([niche.value for niche in niches])
        )
    ).all() if niches else []
    recommended_keys = {
        item.capability_key for item in activity_rules if item.role == "REQUIRED"
    }
    suggested_addons = {
        item.capability_key for item in activity_rules if item.role == "OPTIONAL"
    }
    return [
        CapabilityCatalogItem(
            key=contract.key,
            name=contract.name,
            version=contract.version,
            scope=contract.scope.value,
            description=contract.description,
            requires=list(contract.requires),
            enabled=key in enabled_keys,
            status=(
                EntitlementStatusEnum.ACTIVE.value
                if key in enabled_keys
                else EntitlementStatusEnum.SUSPENDED.value
            ),
            contract_limits=dict(entitlements[key].contract_limits) if key in entitlements else {},
            required=key in recommended_keys,
            addon=key in suggested_addons,
            recommended=key in recommended_keys or key in suggested_addons,
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
    if latest_contract(session, tenant_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Este tenant possui contrato versionado. Altere capabilities pelo editor do contrato "
                "para criar uma nova versão auditada."
            ),
        )
    if capability_key not in CAPABILITY_REGISTRY:
        raise HTTPException(status_code=404, detail="Capacidade não encontrada no catálogo.")
    if data.enabled and capability_key not in IMPLEMENTED_CAPABILITIES:
        raise HTTPException(
            status_code=409,
            detail="Capability possui contrato arquitetural, mas seu módulo executável ainda não passou pelo gate.",
        )

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


@router.put("/platform/tenants/{tenant_id}/contract-administrator", response_model=PlatformTenantInviteResult)
def replace_platform_tenant_administrator(
    tenant_id: uuid.UUID,
    data: PlatformTenantAdministratorReplace,
    principal: AuthPrincipal = Depends(get_current_principal),
    session: Session = Depends(get_session),
):
    actor = require_platform_role(session, principal, PLATFORM_MANAGERS, require_aal2=True)
    assert actor is not None
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado.")
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Informe um e-mail válido.")

    current_membership = None
    if data.current_membership_id is not None:
        current_membership = session.get(Membership, data.current_membership_id)
        if (
            current_membership is None
            or current_membership.tenant_id != tenant_id
            or current_membership.role not in {RoleEnum.TENANT_OWNER, RoleEnum.OWNER, RoleEnum.ADMIN}
        ):
            raise HTTPException(status_code=404, detail="Administrador contratual atual não encontrado.")
    else:
        current_membership = session.exec(select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.role.in_({RoleEnum.TENANT_OWNER, RoleEnum.OWNER, RoleEnum.ADMIN}),
            Membership.status.in_({MembershipStatusEnum.ACTIVE, MembershipStatusEnum.INVITED}),
        ).order_by(Membership.created_at)).first()

    target_user = session.exec(select(User).where(User.email == email)).first()
    delivery_status = "IDENTIDADE_EXISTENTE"
    provider_subject = None
    if target_user is None:
        invited = supabase_admin.invite_user(email=email, full_name=data.full_name.strip(), tenant_id=str(tenant_id))
        provider_subject = str(invited["id"])
        delivery_status = "ENVIADO"

    target_membership = None
    if target_user is not None:
        target_user.full_name = data.full_name.strip()
        session.add(target_user)
        target_membership = session.exec(select(Membership).where(
            Membership.user_id == target_user.id,
            Membership.tenant_id == tenant_id,
        )).first()
    if target_membership is None:
        target_membership = identity_service.provision_tenant_access(
            session, tenant=tenant, email=email, full_name=data.full_name.strip(),
            role=RoleEnum.TENANT_OWNER, store_id=None, actor_id=actor.id,
            provider_subject=provider_subject,
        )
        target_user = session.get(User, target_membership.user_id)
    else:
        target_membership.role = RoleEnum.TENANT_OWNER
        target_membership.status = MembershipStatusEnum.ACTIVE
        target_membership.store_id = None
        target_membership.updated_at = datetime.utcnow()
        session.add(target_membership)
    assert target_user is not None

    if current_membership is not None and current_membership.id != target_membership.id:
        current_membership.status = MembershipStatusEnum.SUSPENDED
        current_membership.updated_at = datetime.utcnow()
        session.add(current_membership)

    local, domain = email.split("@", 1)
    masked = f"{local[:2]}{'*' * max(1, len(local) - 2)}@{domain}"
    session.add(IdentityDeliveryEvent(
        tenant_id=tenant_id, membership_id=target_membership.id, kind="CONTRACT_ADMIN_REPLACEMENT",
        recipient_masked=masked, provider="SUPABASE_SMTP", status=delivery_status,
        sanitized_detail="Administrador contratual atualizado pelo Dashem Control; credenciais e tokens não são armazenados.",
    ))
    payload = {
        "tenant_id": str(tenant_id), "previous_membership_id": str(current_membership.id) if current_membership else None,
        "membership_id": str(target_membership.id), "reason": data.reason.strip(), "actor_id": str(actor.id),
    }
    reliability_service.write_audit_and_outbox(
        session, tenant_id=tenant_id, store_id=None, actor_id=actor.id,
        action="platform.tenant.contract_administrator_replaced", target=f"tenant:{tenant_id}:contract-administrator",
        audit_payload=payload, aggregate_type="tenant_contract_administrator", aggregate_id=str(tenant_id),
        event_type="platform.tenant.contract_administrator_replaced", outbox_payload=payload,
    )
    session.commit()
    return PlatformTenantInviteResult(
        access=_tenant_access_read(target_membership, target_user, None), delivery_status=delivery_status,
    )


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
    local, domain = email.split("@", 1)
    masked = f"{local[:2]}{'*' * max(1, len(local) - 2)}@{domain}"
    session.add(IdentityDeliveryEvent(
        tenant_id=tenant_id, membership_id=membership.id, kind="CONTRACT_ADMIN_INVITE",
        recipient_masked=masked, provider="SUPABASE_SMTP", status=delivery_status,
        sanitized_detail="Convite solicitado pelo Dashem Control; credenciais e tokens não são armazenados.",
    ))
    session.commit()
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
    store.tax_id = _normalize_tax_id(data.tax_id)
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
    try:
        require_count_capacity(session, tenant_id, CountResource.UNITS)
    except QuotaCapacityExceededError as exc:
        raise HTTPException(status_code=409, detail=exc.evaluation.reason) from exc
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
    try:
        require_count_capacity(session, data.tenant_id, CountResource.UNITS)
    except QuotaCapacityExceededError as exc:
        raise HTTPException(status_code=409, detail=exc.evaluation.reason) from exc
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
