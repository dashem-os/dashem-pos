import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, JSON, String, Text, text
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.core.db_types import EnumString


class LeadStatusEnum(str, Enum):
    NEW = "NEW"
    QUALIFIED = "QUALIFIED"
    ONBOARDING = "ONBOARDING"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class PlatformRoleEnum(str, Enum):
    PLATFORM_OWNER = "PLATFORM_OWNER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    SALES = "SALES"
    SUPPORT = "SUPPORT"
    OPERATIONS = "OPERATIONS"
    AUDITOR = "AUDITOR"


class CapabilityScopeEnum(str, Enum):
    TENANT = "TENANT"
    STORE = "STORE"
    TERMINAL = "TERMINAL"


class CapabilityStatusEnum(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class EntitlementStatusEnum(str, Enum):
    CONTRACTED = "CONTRACTED"
    CONFIGURED = "CONFIGURED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ControlStatusEnum(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CANCELED = "CANCELED"


class SupportGrantStatusEnum(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PlatformMembership(SQLModel, table=True):
    __tablename__ = "platform_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_platform_membership_user"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    role: PlatformRoleEnum = Field(sa_column=Column(String, nullable=False, index=True))
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PlatformPermissionDefinition(SQLModel, table=True):
    """Permission contract owned by the Control plane, never by a tenant."""

    __tablename__ = "platform_permission_definitions"

    key: str = Field(primary_key=True, max_length=120)
    name: str = Field(max_length=160)
    description: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PlatformRolePermission(SQLModel, table=True):
    __tablename__ = "platform_role_permissions"
    __table_args__ = (
        UniqueConstraint("role", "permission_key", name="uq_platform_role_permission"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    role: PlatformRoleEnum = Field(sa_column=Column(String, nullable=False, index=True))
    permission_key: str = Field(
        foreign_key="platform_permission_definitions.key",
        ondelete="CASCADE",
        index=True,
        max_length=120,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PlatformPermissionGrant(SQLModel, table=True):
    """Per-membership override. Explicit denial wins over the role default."""

    __tablename__ = "platform_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "platform_membership_id", "permission_key",
            name="uq_platform_membership_permission_grant",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    platform_membership_id: uuid.UUID = Field(
        foreign_key="platform_memberships.id", ondelete="CASCADE", index=True
    )
    permission_key: str = Field(
        foreign_key="platform_permission_definitions.key",
        ondelete="CASCADE",
        index=True,
        max_length=120,
    )
    allowed: bool = Field(nullable=False)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    granted_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Lead(SQLModel, table=True):
    __tablename__ = "platform_leads"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_name: str = Field(index=True)
    contact_name: str
    email: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = Field(default=None, index=True)
    source: Optional[str] = Field(default=None, index=True)
    status: LeadStatusEnum = Field(
        default=LeadStatusEnum.NEW,
        sa_column=Column(String, nullable=False, index=True),
    )
    notes: Optional[str] = None
    owner_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    converted_tenant_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tenants.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    converted_at: Optional[datetime] = None


class CapabilityDefinition(SQLModel, table=True):
    __tablename__ = "capability_definitions"

    key: str = Field(primary_key=True, max_length=80)
    name: str = Field(max_length=160)
    version: str = Field(default="1.0.0", max_length=32)
    description: str
    scope: CapabilityScopeEnum = Field(sa_column=Column(EnumString(CapabilityScopeEnum), nullable=False, index=True))
    status: CapabilityStatusEnum = Field(
        default=CapabilityStatusEnum.ACTIVE,
        sa_column=Column(EnumString(CapabilityStatusEnum), nullable=False, index=True),
    )
    configuration_schema: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CapabilityDependency(SQLModel, table=True):
    __tablename__ = "capability_dependencies"
    __table_args__ = (
        UniqueConstraint("capability_key", "requires_key", name="uq_capability_dependency"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    capability_key: str = Field(foreign_key="capability_definitions.key", index=True)
    requires_key: str = Field(foreign_key="capability_definitions.key", index=True)
    minimum_version: Optional[str] = Field(default=None, max_length=32)


class CapabilityProfile(SQLModel, table=True):
    __tablename__ = "capability_profiles"

    key: str = Field(primary_key=True, max_length=80)
    name: str = Field(max_length=160)
    description: str
    version: str = Field(default="1.0.0", max_length=32)
    is_active: bool = Field(default=True, index=True)


class CapabilityProfileItem(SQLModel, table=True):
    __tablename__ = "capability_profile_items"
    __table_args__ = (
        UniqueConstraint("profile_key", "capability_key", name="uq_capability_profile_item"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    profile_key: str = Field(foreign_key="capability_profiles.key", index=True)
    capability_key: str = Field(foreign_key="capability_definitions.key", index=True)
    required: bool = Field(default=True)
    default_configuration: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )


class TenantCapability(SQLModel, table=True):
    __tablename__ = "tenant_capabilities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_capability_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    key: str = Field(foreign_key="capability_definitions.key", index=True)
    enabled: bool = Field(default=True, index=True)
    status: EntitlementStatusEnum = Field(
        default=EntitlementStatusEnum.ACTIVE,
        sa_column=Column(EnumString(EntitlementStatusEnum), nullable=False, index=True),
    )
    contract_limits: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    configuration: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StoreCapabilityOverride(SQLModel, table=True):
    __tablename__ = "store_capability_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "store_id", "key", name="uq_store_capability_override"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    key: str = Field(foreign_key="capability_definitions.key", index=True)
    enabled: bool = Field(default=True, index=True)
    configuration: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TenantContract(SQLModel, table=True):
    """Versioned commercial contract snapshot owned by the Control plane."""

    __tablename__ = "tenant_contracts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_tenant_contract_version"),
        CheckConstraint("schema_version >= 1", name="ck_tenant_contract_schema_version_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    version: int = Field(default=1)
    status: str = Field(default="DRAFT", index=True, max_length=32)
    plan_id: Optional[uuid.UUID] = Field(default=None, foreign_key="service_plans.id", index=True)
    plan_revision_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="service_plan_revisions.id", index=True
    )
    limits: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    capability_keys: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, default=list))
    activity_keys: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, default=list))
    capability_entitlements: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, default=list)
    )
    limit_entitlements: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    storage_entitlement: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict)
    )
    schema_version: int = Field(default=2, ge=1)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    reason: str = Field(sa_column=Column(Text, nullable=False))
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class TenantOnboardingCheckpoint(SQLModel, table=True):
    __tablename__ = "tenant_onboarding_checkpoints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_onboarding_checkpoint"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    key: str = Field(index=True, max_length=80)
    label: str = Field(max_length=180)
    status: str = Field(default="PENDING", index=True, max_length=32)
    evidence: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    completed_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class IdentityDeliveryEvent(SQLModel, table=True):
    """Sanitized identity/e-mail delivery history; provider tokens never enter this table."""

    __tablename__ = "identity_delivery_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    membership_id: Optional[uuid.UUID] = Field(default=None, foreign_key="memberships.id", index=True)
    kind: str = Field(index=True, max_length=60)
    recipient_masked: str = Field(max_length=254)
    provider: str = Field(default="SUPABASE_SMTP", max_length=60)
    status: str = Field(index=True, max_length=32)
    provider_message_id: Optional[str] = Field(default=None, max_length=180)
    sanitized_detail: Optional[str] = Field(default=None, max_length=500)
    occurred_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class AssistedSupportGrant(SQLModel, table=True):
    __tablename__ = "assisted_support_grants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    requested_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    approved_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, default=list))
    reason: str = Field(sa_column=Column(Text, nullable=False))
    status: SupportGrantStatusEnum = Field(
        default=SupportGrantStatusEnum.PENDING,
        sa_column=Column(EnumString(SupportGrantStatusEnum), nullable=False, index=True),
    )
    expires_at: datetime = Field(index=True)
    approved_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PlatformIncident(SQLModel, table=True):
    __tablename__ = "platform_incidents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tenants.id", index=True)
    title: str = Field(max_length=180)
    severity: str = Field(index=True, max_length=16)
    status: ControlStatusEnum = Field(
        default=ControlStatusEnum.OPEN,
        sa_column=Column(EnumString(ControlStatusEnum), nullable=False, index=True),
    )
    component: str = Field(index=True, max_length=80)
    sanitized_summary: str = Field(sa_column=Column(Text, nullable=False))
    correlation_id: Optional[str] = Field(default=None, index=True, max_length=120)
    opened_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    resolved_by: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    opened_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    resolved_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CapabilityProfileRevision(SQLModel, table=True):
    __tablename__ = "capability_profile_revisions"
    __table_args__ = (
        UniqueConstraint("profile_key", "version", name="uq_capability_profile_revision"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    profile_key: str = Field(index=True, max_length=80)
    version: str = Field(index=True, max_length=32)
    name: str = Field(max_length=160)
    description: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default="ACTIVE", index=True, max_length=32)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CapabilityProfileRevisionItem(SQLModel, table=True):
    __tablename__ = "capability_profile_revision_items"
    __table_args__ = (
        UniqueConstraint("revision_id", "capability_key", name="uq_capability_profile_revision_item"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    revision_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("capability_profile_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    capability_key: str = Field(foreign_key="capability_definitions.key", index=True)
    required: bool = Field(default=True)
    default_configuration: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))


class TenantProfileAssignment(SQLModel, table=True):
    __tablename__ = "tenant_profile_assignments"
    __table_args__ = (
        Index(
            "uq_tenant_active_profile_assignment",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    revision_id: uuid.UUID = Field(foreign_key="capability_profile_revisions.id", index=True)
    status: str = Field(default="ACTIVE", index=True, max_length=32)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    assigned_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    assigned_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    ended_at: Optional[datetime] = None


class ModuleContribution(SQLModel, table=True):
    __tablename__ = "module_contributions"
    __table_args__ = (
        UniqueConstraint("surface", "contribution_key", name="uq_module_contribution_surface_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    capability_key: Optional[str] = Field(default=None, foreign_key="capability_definitions.key", index=True)
    surface: str = Field(index=True, max_length=60)
    contribution_key: str = Field(index=True, max_length=100)
    label: str = Field(max_length=160)
    group_key: Optional[str] = Field(default=None, max_length=80)
    route: Optional[str] = Field(default=None, max_length=180)
    permission_key: Optional[str] = Field(default=None, max_length=120)
    implementation_key: str = Field(max_length=120)
    sort_order: int = Field(default=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    is_active: bool = Field(default=True, index=True)


class CapabilityConflict(SQLModel, table=True):
    __tablename__ = "capability_conflicts"
    __table_args__ = (
        UniqueConstraint("capability_key", "conflicts_with_key", name="uq_capability_conflict"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    capability_key: str = Field(foreign_key="capability_definitions.key", index=True)
    conflicts_with_key: str = Field(foreign_key="capability_definitions.key", index=True)
    reason: str = Field(sa_column=Column(Text, nullable=False))


class OperationalHardeningRun(SQLModel, table=True):
    __tablename__ = "operational_hardening_runs"
    __table_args__ = (
        CheckConstraint("rpo_target_minutes >= 0", name="ck_hardening_rpo_nonnegative"),
        CheckConstraint("rto_target_minutes >= 1", name="ck_hardening_rto_positive"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    release_sha: str = Field(index=True, max_length=64)
    environment: str = Field(index=True, max_length=40)
    status: str = Field(default="IN_PROGRESS", index=True, max_length=32)
    rpo_target_minutes: int = Field(default=15, ge=0)
    rto_target_minutes: int = Field(default=60, ge=1)
    initiated_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OperationalHardeningEvidence(SQLModel, table=True):
    __tablename__ = "operational_hardening_evidence"
    __table_args__ = (
        UniqueConstraint("run_id", "check_key", name="uq_operational_hardening_evidence_check"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("operational_hardening_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    check_key: str = Field(index=True, max_length=80)
    category: str = Field(index=True, max_length=60)
    status: str = Field(index=True, max_length=20)
    evidence_ref: str = Field(max_length=500)
    observed: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    recorded_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    measured_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CommercialPilot(SQLModel, table=True):
    __tablename__ = "commercial_pilots"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    store_id: uuid.UUID = Field(foreign_key="stores.id", index=True)
    hardening_run_id: uuid.UUID = Field(foreign_key="operational_hardening_runs.id", index=True)
    status: str = Field(default="READY_FOR_FIELD_VALIDATION", index=True, max_length=40)
    scope: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    created_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    field_started_at: Optional[datetime] = None
    field_completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PilotObservation(SQLModel, table=True):
    __tablename__ = "pilot_observations"
    __table_args__ = (
        UniqueConstraint("pilot_id", "source_ref", name="uq_pilot_observation_source"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pilot_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("commercial_pilots.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    task_type: str = Field(index=True, max_length=60)
    source_ref: str = Field(max_length=180)
    metrics: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    observed_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    observed_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PilotIncidentGate(SQLModel, table=True):
    __tablename__ = "pilot_incident_gates"
    __table_args__ = (
        UniqueConstraint("pilot_id", "incident_id", name="uq_pilot_incident_gate"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    pilot_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("commercial_pilots.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    incident_id: uuid.UUID = Field(foreign_key="platform_incidents.id", index=True)
    blocks_expansion: bool = Field(default=True, index=True)
    decision_reason: str = Field(sa_column=Column(Text, nullable=False))
    decided_by: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
