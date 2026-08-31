from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.storage import (
    StorageMeasurementCreate,
    _measurement_fingerprint,
    _safe_locator_reference,
)
from app.modules.governance.contracts import MeasurementStatus, QuotaDecision
from app.services.storage_quota_service import evaluate_storage_quota


def test_storage_without_reconciled_inventory_is_unknown_and_fail_closed():
    evaluation = evaluate_storage_quota(
        contracted_bytes=1024 * 1024,
        measurement_status=MeasurementStatus.NOT_MEASURED,
        used_bytes=None,
        reserved_bytes=0,
        requested_bytes=1,
        unavailable_reason="Nenhum inventário persistido.",
    )

    assert evaluation.decision == QuotaDecision.UNKNOWN
    assert evaluation.occupied is None
    assert evaluation.remaining is None
    assert evaluation.reason == "Nenhum inventário persistido."


def test_storage_quota_counts_usage_and_concurrent_reservations():
    evaluation = evaluate_storage_quota(
        contracted_bytes=1000,
        measurement_status=MeasurementStatus.RECONCILED,
        used_bytes=700,
        reserved_bytes=100,
        requested_bytes=50,
    )

    assert evaluation.decision == QuotaDecision.WARNING
    assert evaluation.occupied == 800
    assert evaluation.remaining == 200

    denied = evaluate_storage_quota(
        contracted_bytes=1000,
        measurement_status=MeasurementStatus.RECONCILED,
        used_bytes=700,
        reserved_bytes=250,
        requested_bytes=51,
    )
    assert denied.decision == QuotaDecision.DENIED


def test_measurement_fingerprint_is_server_derived_and_source_order_independent():
    tenant_id = uuid4()
    measured_at = datetime(2026, 8, 31, 10, 0, 0)
    first = StorageMeasurementCreate(
        status="RECONCILED",
        used_bytes=42,
        object_count=2,
        source_keys=["documents", "catalog-images"],
        watermark="inventory:42",
        evidence_reference="provider-job:abc",
        measured_at=measured_at,
    )
    second = first.model_copy(update={"source_keys": list(reversed(first.source_keys))})

    assert _measurement_fingerprint(tenant_id, first) == _measurement_fingerprint(tenant_id, second)

    utc_aware = first.model_copy(update={"measured_at": measured_at.replace(tzinfo=timezone.utc)})
    assert _measurement_fingerprint(tenant_id, first) == _measurement_fingerprint(tenant_id, utc_aware)


def test_physical_locator_rejects_credentials_and_signed_queries():
    assert _safe_locator_reference("s3://dashem/tenant-a/documents") == "s3://dashem/tenant-a/documents"
    with pytest.raises(HTTPException, match="sem credenciais"):
        _safe_locator_reference("https://provider.test/bucket?token=secret")
