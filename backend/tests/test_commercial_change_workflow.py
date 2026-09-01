from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.endpoints.commercial_requests import (
    CommercialDecisionCreate,
    _assert_request_applied,
)
from app.models.platform import CommercialChangeRequestRecord, TenantContract


def _contract(**changes) -> TenantContract:
    values = {
        "tenant_id": uuid4(),
        "version": 2,
        "status": "ACTIVE",
        "limits": {"users": 10, "devices": 2, "units": 1, "storage_mib": 1024},
        "capability_keys": ["catalog"],
        "activity_keys": ["RETAIL"],
        "reason": "Owner approval",
        "created_by": uuid4(),
    }
    values.update(changes)
    return TenantContract(**values)


def _request(kind: str, payload: dict) -> CommercialChangeRequestRecord:
    return CommercialChangeRequestRecord(
        tenant_id=uuid4(), kind=kind, payload=payload, reason="Tenant need",
        requested_by=uuid4(), source_contract_id=uuid4(), source_contract_version=1,
    )


def test_approval_must_materialize_requested_entitlement_in_new_contract():
    request = _request("USER_LIMIT", {"resource": "users", "requested_limit": 20})

    with pytest.raises(HTTPException, match="não aplica integralmente"):
        _assert_request_applied(request, _contract())

    _assert_request_applied(request, _contract(limits={"users": 20}))


def test_capability_and_activity_approvals_are_verified_against_snapshot():
    capability = _request("CAPABILITY", {"capability_key": "payments", "action": "ENABLE"})
    activity = _request("ACTIVITY", {"activity_key": "FOOD_SERVICE", "action": "ADD"})

    _assert_request_applied(capability, _contract(capability_keys=["catalog", "payments"]))
    _assert_request_applied(activity, _contract(activity_keys=["RETAIL", "FOOD_SERVICE"]))


def test_owner_decision_payload_cannot_smuggle_a_handwritten_contract():
    with pytest.raises(ValidationError):
        CommercialDecisionCreate.model_validate({
            "decision": "APPROVE",
            "reason": "Approved by Owner",
            "contract": {"billing_day": 1},
        })
