from datetime import datetime
from uuid import uuid4

import pytest

from app.modules.governance.contracts import (
    CountResource,
    CountUsageSnapshot,
    QuotaDecision,
)
from app.services.quota_policy_service import (
    QuotaCapacityExceededError,
    evaluate_count_quota,
)


def _usage(*, configured: int, reserved: int = 0) -> CountUsageSnapshot:
    return CountUsageSnapshot(
        tenant_id=uuid4(),
        resource=CountResource.USERS,
        configured=configured,
        reserved=reserved,
        observed=configured,
        measured_at=datetime.utcnow(),
    )


def test_quota_policy_warns_before_the_limit_and_preserves_usage_dimensions():
    usage = _usage(configured=7, reserved=1)

    evaluation = evaluate_count_quota(
        resource=CountResource.USERS,
        contracted=10,
        usage=usage,
        requested=0,
    )

    assert evaluation.decision == QuotaDecision.WARNING
    assert evaluation.occupied == 8
    assert evaluation.remaining == 2


def test_quota_policy_denies_only_when_the_requested_capacity_exceeds_contract():
    usage = _usage(configured=8, reserved=2)

    evaluation = evaluate_count_quota(
        resource=CountResource.USERS,
        contracted=10,
        usage=usage,
        requested=1,
    )

    assert evaluation.decision == QuotaDecision.DENIED
    assert evaluation.occupied == 10
    assert evaluation.requested == 1


def test_missing_contract_limit_is_unknown_instead_of_fabricated():
    evaluation = evaluate_count_quota(
        resource=CountResource.USERS,
        contracted=None,
        usage=_usage(configured=3),
    )

    assert evaluation.decision == QuotaDecision.UNKNOWN
    assert evaluation.remaining is None
    assert "não há teto verificável" in evaluation.reason


def test_capacity_error_retains_the_canonical_evaluation():
    evaluation = evaluate_count_quota(
        resource=CountResource.USERS,
        contracted=1,
        usage=_usage(configured=1),
        requested=1,
    )

    error = QuotaCapacityExceededError(evaluation)
    assert error.evaluation is evaluation
    assert str(error) == evaluation.reason
