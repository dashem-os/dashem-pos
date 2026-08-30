from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.modules.governance import contracts as governance_contracts
from app.modules.governance.contracts import (
    CapabilityEntitlement,
    ContractEntitlementSnapshot,
    CountResource,
    CountUsageSnapshot,
    EntitlementSource,
    LimitEntitlement,
    MeasurementStatus,
    OwnerDecision,
    OwnerDecisionKind,
    StorageEntitlement,
    StorageUsageSnapshot,
)


def test_governance_contracts_remain_framework_and_persistence_agnostic():
    source = Path(governance_contracts.__file__).read_text(encoding="utf-8")

    for forbidden_dependency in ("fastapi", "sqlmodel", "sqlalchemy", "app.models"):
        assert forbidden_dependency not in source


def test_contract_preserves_multiple_commercial_activities_without_primary_inference():
    snapshot = ContractEntitlementSnapshot(
        tenant_id=uuid4(),
        contract_version=3,
        plan_revision_id=uuid4(),
        activity_keys=("RETAIL", "FOOD_SERVICE"),
        capabilities=(
            CapabilityEntitlement(
                key="catalog",
                sources=frozenset(
                    {
                        EntitlementSource.PLAN,
                        EntitlementSource.ACTIVITY,
                    }
                ),
            ),
        ),
        limits=(
            LimitEntitlement(
                resource=CountResource.USERS,
                limit=40,
                sources=frozenset({EntitlementSource.PLAN}),
            ),
        ),
        storage=StorageEntitlement(
            limit_bytes=16 * 1024 * 1024,
            sources=frozenset({EntitlementSource.PLAN}),
        ),
        effective_at=datetime.utcnow(),
    )

    assert snapshot.activity_keys == ("RETAIL", "FOOD_SERVICE")
    assert snapshot.capabilities[0].sources == frozenset(
        {EntitlementSource.PLAN, EntitlementSource.ACTIVITY}
    )


def test_duplicate_activities_are_rejected_instead_of_being_silently_collapsed():
    with pytest.raises(ValueError, match="activities must be unique"):
        ContractEntitlementSnapshot(
            tenant_id=uuid4(),
            contract_version=1,
            plan_revision_id=uuid4(),
            activity_keys=("RETAIL", "RETAIL"),
            capabilities=(),
            limits=(),
            storage=StorageEntitlement(
                limit_bytes=None,
                sources=frozenset({EntitlementSource.OWNER_EXCEPTION}),
            ),
            effective_at=datetime.utcnow(),
        )


def test_configured_and_reserved_are_distinct_from_the_contracted_limit():
    tenant_id = uuid4()
    entitlement = LimitEntitlement(
        resource=CountResource.USERS,
        limit=40,
        sources=frozenset({EntitlementSource.PLAN}),
    )
    usage = CountUsageSnapshot(
        tenant_id=tenant_id,
        resource=CountResource.USERS,
        configured=7,
        reserved=2,
        observed=5,
        measured_at=datetime.utcnow(),
    )

    assert entitlement.limit == 40
    assert usage.configured == 7
    assert usage.occupied == 9
    assert usage.observed == 5


def test_storage_not_measured_cannot_be_represented_as_zero_usage():
    with pytest.raises(ValueError, match="cannot claim a usage value"):
        StorageUsageSnapshot(
            tenant_id=uuid4(),
            used_bytes=0,
            reserved_bytes=0,
            status=MeasurementStatus.NOT_MEASURED,
            measured_at=None,
        )

    transparent = StorageUsageSnapshot(
        tenant_id=uuid4(),
        used_bytes=None,
        reserved_bytes=0,
        status=MeasurementStatus.NOT_MEASURED,
        measured_at=None,
    )
    assert transparent.used_bytes is None


def test_contracts_are_immutable_and_owner_decisions_require_a_reason():
    entitlement = CapabilityEntitlement(
        key="payments",
        sources=frozenset({EntitlementSource.ADDON}),
    )
    with pytest.raises(FrozenInstanceError):
        entitlement.key = "catalog"  # type: ignore[misc]

    with pytest.raises(ValueError, match="require a reason"):
        OwnerDecision(
            request_id=uuid4(),
            decision=OwnerDecisionKind.DECLINE,
            decided_by=uuid4(),
            reason="   ",
        )
