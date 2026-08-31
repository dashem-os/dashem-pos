from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.storage import (
    StorageMeasurementCreate,
    _measurement_fingerprint,
    _safe_locator_reference,
)
from app.core.config import Settings
from app.modules.governance.contracts import MeasurementStatus, QuotaDecision
from app.services.storage_quota_service import evaluate_provider_capacity, evaluate_storage_quota


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


def test_storage_warning_thresholds_are_configuration_not_provider_assumptions(monkeypatch):
    monkeypatch.setattr("app.services.storage_quota_service.settings.STORAGE_TENANT_WARNING_PERCENT", 70)
    monkeypatch.setattr("app.services.storage_quota_service.settings.STORAGE_TENANT_CRITICAL_PERCENT", 85)
    preventive = evaluate_storage_quota(
        contracted_bytes=1000, measurement_status=MeasurementStatus.RECONCILED,
        used_bytes=699, reserved_bytes=0, requested_bytes=1,
    )
    critical = evaluate_storage_quota(
        contracted_bytes=1000, measurement_status=MeasurementStatus.RECONCILED,
        used_bytes=849, reserved_bytes=0, requested_bytes=1,
    )
    assert preventive.decision == QuotaDecision.WARNING
    assert "70%" in preventive.reason
    assert critical.decision == QuotaDecision.WARNING
    assert "85%" in critical.reason


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


def test_provider_capacity_never_assumes_free_plan_or_zero_usage():
    unknown = evaluate_provider_capacity(
        configured=False, capacity_bytes=None, reserved_margin_bytes=0,
        measurement_status="NOT_CONFIGURED", used_bytes=None, reserved_bytes=0,
        requested_bytes=1, unavailable_reason="Capacidade não configurada.",
    )
    assert unknown.decision == QuotaDecision.UNKNOWN
    assert unknown.contracted is None
    assert unknown.occupied is None
    assert unknown.remaining is None


def test_provider_capacity_respects_margin_and_denies_global_oversubscription():
    denied = evaluate_provider_capacity(
        configured=True, capacity_bytes=1000, reserved_margin_bytes=100,
        measurement_status="RECONCILED", used_bytes=800, reserved_bytes=50,
        requested_bytes=51, unavailable_reason="",
    )
    assert denied.contracted == 900
    assert denied.occupied == 850
    assert denied.remaining == 50
    assert denied.decision == QuotaDecision.DENIED


def test_empty_provider_capacity_environment_remains_explicitly_unconfigured():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://test:test@localhost/test",
        SECRET_KEY="test-secret-key-with-at-least-32-characters",
        SUPABASE_STORAGE_CAPACITY_BYTES="",
    )
    assert configured.SUPABASE_STORAGE_CAPACITY_BYTES is None
    assert configured.supabase_storage_configured is False


def test_managed_buckets_cannot_drift_from_versioned_supabase_policies():
    with pytest.raises(ValueError, match="versioned restrictive policies"):
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://test:test@localhost/test",
            SECRET_KEY="test-secret-key-with-at-least-32-characters",
            SUPABASE_STORAGE_BUCKETS="tenant-assets,unprotected-bucket",
        )
