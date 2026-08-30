"""Pure domain contracts for Owner governance.

This module intentionally has no dependency on persistence, FastAPI or a
provider SDK.  It names the boundaries that later sprints will implement.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional, Protocol
from uuid import UUID


class CountResource(str, Enum):
    USERS = "USERS"
    DEVICES = "DEVICES"
    UNITS = "UNITS"


class EntitlementSource(str, Enum):
    PLAN = "PLAN"
    ACTIVITY = "ACTIVITY"
    ADDON = "ADDON"
    DEPENDENCY = "DEPENDENCY"
    OWNER_DECISION = "OWNER_DECISION"
    OWNER_EXCEPTION = "OWNER_EXCEPTION"
    LEGACY_MIGRATED = "LEGACY_MIGRATED"


class MeasurementStatus(str, Enum):
    NOT_MEASURED = "NOT_MEASURED"
    PARTIAL = "PARTIAL"
    RECONCILED = "RECONCILED"
    DIVERGENT = "DIVERGENT"
    UNAVAILABLE = "UNAVAILABLE"


class QuotaDecision(str, Enum):
    ALLOWED = "ALLOWED"
    WARNING = "WARNING"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


class CommercialChangeKind(str, Enum):
    ACTIVITY = "ACTIVITY"
    CAPABILITY = "CAPABILITY"
    USER_LIMIT = "USER_LIMIT"
    DEVICE_LIMIT = "DEVICE_LIMIT"
    UNIT_LIMIT = "UNIT_LIMIT"
    STORAGE_LIMIT = "STORAGE_LIMIT"
    INTEGRATION = "INTEGRATION"


class CommercialRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class OwnerDecisionKind(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative.")


@dataclass(frozen=True)
class CapabilityEntitlement:
    key: str
    sources: frozenset[EntitlementSource]

    def __post_init__(self) -> None:
        if not self.key or self.key.lower() != self.key:
            raise ValueError("Capability keys must be non-empty lowercase identifiers.")
        if not self.sources:
            raise ValueError("A capability entitlement must declare at least one source.")


@dataclass(frozen=True)
class LimitEntitlement:
    resource: CountResource
    limit: Optional[int]
    sources: frozenset[EntitlementSource]

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("An explicit contracted limit must be positive.")
        if not self.sources:
            raise ValueError("A limit entitlement must declare at least one source.")


@dataclass(frozen=True)
class StorageEntitlement:
    limit_bytes: Optional[int]
    sources: frozenset[EntitlementSource]

    def __post_init__(self) -> None:
        if self.limit_bytes is not None and self.limit_bytes < 1:
            raise ValueError("An explicit storage entitlement must be positive.")
        if not self.sources:
            raise ValueError("A storage entitlement must declare at least one source.")


@dataclass(frozen=True)
class CommercialOffer:
    plan_revision_id: UUID
    activity_keys: tuple[str, ...]
    capabilities: tuple[CapabilityEntitlement, ...]
    limits: tuple[LimitEntitlement, ...]
    storage: StorageEntitlement

    def __post_init__(self) -> None:
        _validate_entitlement_collections(
            self.activity_keys, self.capabilities, self.limits
        )


def _validate_entitlement_collections(
    activity_keys: tuple[str, ...],
    capabilities: tuple[CapabilityEntitlement, ...],
    limits: tuple[LimitEntitlement, ...],
) -> None:
    if len(set(activity_keys)) != len(activity_keys):
        raise ValueError("Contract activities must be unique.")
    if any(not key or key.upper() != key for key in activity_keys):
        raise ValueError("Activity keys must be non-empty uppercase identifiers.")
    capability_keys = [item.key for item in capabilities]
    if len(set(capability_keys)) != len(capability_keys):
        raise ValueError("Capability entitlements must be unique.")
    resources = [item.resource for item in limits]
    if len(set(resources)) != len(resources):
        raise ValueError("Limit entitlements must be unique by resource.")


@dataclass(frozen=True)
class ContractEntitlementSnapshot:
    tenant_id: UUID
    contract_version: int
    plan_revision_id: UUID
    activity_keys: tuple[str, ...]
    capabilities: tuple[CapabilityEntitlement, ...]
    limits: tuple[LimitEntitlement, ...]
    storage: StorageEntitlement
    effective_at: datetime

    def __post_init__(self) -> None:
        if self.contract_version < 1:
            raise ValueError("Contract version must be positive.")
        _validate_entitlement_collections(
            self.activity_keys, self.capabilities, self.limits
        )


@dataclass(frozen=True)
class CountUsageSnapshot:
    tenant_id: UUID
    resource: CountResource
    configured: int
    reserved: int
    observed: Optional[int]
    measured_at: datetime

    def __post_init__(self) -> None:
        _require_non_negative("configured", self.configured)
        _require_non_negative("reserved", self.reserved)
        if self.observed is not None:
            _require_non_negative("observed", self.observed)

    @property
    def occupied(self) -> int:
        return self.configured + self.reserved


@dataclass(frozen=True)
class StorageUsageSnapshot:
    tenant_id: UUID
    used_bytes: Optional[int]
    reserved_bytes: int
    status: MeasurementStatus
    measured_at: Optional[datetime]

    def __post_init__(self) -> None:
        _require_non_negative("reserved_bytes", self.reserved_bytes)
        if self.used_bytes is not None:
            _require_non_negative("used_bytes", self.used_bytes)
        if (
            self.status == MeasurementStatus.NOT_MEASURED
            and self.used_bytes is not None
        ):
            raise ValueError("Storage not measured cannot claim a usage value.")
        if self.status == MeasurementStatus.RECONCILED:
            if self.used_bytes is None or self.measured_at is None:
                raise ValueError("Reconciled storage requires usage and measurement time.")


@dataclass(frozen=True)
class QuotaEvaluation:
    resource: str
    contracted: Optional[int]
    occupied: Optional[int]
    requested: int
    remaining: Optional[int]
    decision: QuotaDecision
    reason: str

    def __post_init__(self) -> None:
        _require_non_negative("requested", self.requested)
        for name, value in (
            ("contracted", self.contracted),
            ("occupied", self.occupied),
            ("remaining", self.remaining),
        ):
            if value is not None:
                _require_non_negative(name, value)
        if not self.reason.strip():
            raise ValueError("Quota decisions require a reason.")


@dataclass(frozen=True)
class CommercialChangeRequest:
    id: UUID
    tenant_id: UUID
    kind: CommercialChangeKind
    requested_by: UUID
    payload: Mapping[str, object] = field(default_factory=dict)
    status: CommercialRequestStatus = CommercialRequestStatus.DRAFT


@dataclass(frozen=True)
class OwnerDecision:
    request_id: UUID
    decision: OwnerDecisionKind
    decided_by: UUID
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("Owner decisions require a reason.")


class CommercialCatalog(Protocol):
    def resolve_offer(
        self,
        *,
        plan_revision_id: UUID,
        activity_keys: tuple[str, ...],
        addon_keys: tuple[str, ...],
    ) -> CommercialOffer: ...


class ContractEntitlementResolver(Protocol):
    def resolve(self, tenant_id: UUID) -> ContractEntitlementSnapshot: ...


class OperationalUsageProvider(Protocol):
    def snapshot(
        self, tenant_id: UUID, resource: CountResource
    ) -> CountUsageSnapshot: ...


class StorageMeter(Protocol):
    def snapshot(self, tenant_id: UUID) -> StorageUsageSnapshot: ...


class QuotaPolicy(Protocol):
    def evaluate_count(
        self,
        entitlement: LimitEntitlement,
        usage: CountUsageSnapshot,
        *,
        requested: int = 1,
    ) -> QuotaEvaluation: ...

    def evaluate_storage(
        self,
        *,
        entitlement: StorageEntitlement,
        usage: StorageUsageSnapshot,
        requested_bytes: int,
    ) -> QuotaEvaluation: ...


class CapabilityResolver(Protocol):
    def resolve(self, tenant_id: UUID) -> tuple[CapabilityEntitlement, ...]: ...


class ChangeRequestWorkflow(Protocol):
    def submit(
        self, request: CommercialChangeRequest
    ) -> CommercialChangeRequest: ...

    def decide(self, decision: OwnerDecision) -> CommercialChangeRequest: ...
