import uuid
import json

import httpx
import pytest
from pathlib import Path

from app.core.config import settings
from app.services.supabase_credentials import SupabaseCredentialError, supabase_server_headers
from app.services.supabase_storage import (
    SupabaseStorageClient, SupabaseStorageUnavailable, managed_bucket, tenant_object_path,
    validate_content_signature, validate_filename_content_type,
)


@pytest.fixture
def configured_storage(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "private-test-service-key")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_BUCKETS", "tenant-assets,tenant-documents")
    monkeypatch.setattr(settings, "SUPABASE_STORAGE_CAPACITY_BYTES", 1024 * 1024 * 1024)


def test_server_builds_tenant_prefix_and_rejects_path_escape(configured_storage):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    path = tenant_object_path(tenant_a, f"products/{tenant_b}.png")
    assert path == f"{tenant_a}/products/{tenant_b}.png"
    assert not path.startswith(str(tenant_b))
    for unsafe in ("../secret.pdf", "folder//file.png", "folder\\file.png", ""):
        with pytest.raises(ValueError, match="Caminho"):
            tenant_object_path(tenant_a, unsafe)


def test_only_declared_managed_buckets_are_accepted(configured_storage):
    assert managed_bucket("tenant-assets") == "tenant-assets"
    with pytest.raises(ValueError, match="gerenciado"):
        managed_bucket("public-assets")


def test_private_bucket_bootstrap_and_upload_never_expose_service_key(configured_storage):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "tenant-assets", "public": False}])
        if request.url.path.endswith("/bucket"):
            return httpx.Response(200, json={"name": "tenant-documents"})
        return httpx.Response(200, json={"Key": "tenant-assets/object.png"})

    client = SupabaseStorageClient(httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.ensure_private_buckets() == ["tenant-assets", "tenant-documents"]
    stored = client.upload("tenant-assets", f"{uuid.uuid4()}/object.png", b"png", "image/png")
    assert stored.size_bytes == 3
    assert all("private-test-service-key" not in str(request.url) for request in requests)
    assert all(request.headers["authorization"] == "Bearer private-test-service-key" for request in requests)


def test_modern_secret_key_is_sent_only_as_apikey(configured_storage, monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "sb_secret_backend_test")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[
            {"id": "tenant-assets", "public": False},
            {"id": "tenant-documents", "public": False},
        ])

    SupabaseStorageClient(httpx.Client(transport=httpx.MockTransport(handler))).ensure_private_buckets()
    assert requests[0].headers["apikey"] == "sb_secret_backend_test"
    assert "authorization" not in requests[0].headers


def test_publishable_key_is_rejected_for_backend_use(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", "sb_publishable_browser_test")

    with pytest.raises(SupabaseCredentialError, match="chave pública"):
        supabase_server_headers()


def test_public_managed_bucket_is_refused(configured_storage):
    transport = httpx.MockTransport(lambda _: httpx.Response(
        200, json=[{"id": "tenant-assets", "public": True}, {"id": "tenant-documents", "public": False}]
    ))
    with pytest.raises(SupabaseStorageUnavailable, match="público"):
        SupabaseStorageClient(httpx.Client(transport=transport)).ensure_private_buckets()


def test_mime_signature_is_checked_before_upload():
    validate_content_signature(b"\x89PNG\r\n\x1a\nreal", "image/png")
    validate_content_signature(b'{"ok": true}', "application/json")
    with pytest.raises(ValueError, match="MIME"):
        validate_content_signature(b"not-a-png", "image/png")


def test_filename_extension_must_match_declared_mime():
    validate_filename_content_type("products/item.png", "image/png")
    validate_filename_content_type("reports/data.json", "application/json")
    with pytest.raises(ValueError, match="extensão"):
        validate_filename_content_type("products/item.pdf", "image/png")


def test_inventory_uses_provider_metadata_and_global_scope_includes_unmanaged_buckets(configured_storage):
    tenant_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[
                {"id": "tenant-assets", "public": False},
                {"id": "provider-internal", "public": False},
            ])
        payload = json.loads(request.content)
        prefix = payload["prefix"]
        bucket = request.url.path.rsplit("/", 1)[-1]
        if bucket == "tenant-assets" and prefix == str(tenant_id):
            return httpx.Response(200, json=[{
                "id": "one", "name": "photo.png", "metadata": {"size": 12},
                "updated_at": "2026-08-31T10:00:00Z",
            }])
        if bucket == "tenant-assets" and prefix == "":
            return httpx.Response(200, json=[{"id": None, "name": str(tenant_id), "metadata": None}])
        if bucket == "provider-internal" and prefix == "":
            return httpx.Response(200, json=[{
                "id": "system", "name": "system.bin", "metadata": {"size": 7},
                "updated_at": "2026-08-31T11:00:00Z",
            }])
        return httpx.Response(200, json=[])

    client = SupabaseStorageClient(httpx.Client(transport=httpx.MockTransport(handler)))
    tenant = client.inventory("tenant-assets", str(tenant_id))
    assert tenant.used_bytes == 12
    assert tenant.object_count == 1
    assert tenant.object_paths == (f"{tenant_id}/photo.png",)

    project, buckets = client.project_inventory()
    assert buckets == ("provider-internal", "tenant-assets")
    assert project.used_bytes == 19
    assert project.object_count == 2
    assert f"tenant-assets/{tenant_id}/photo.png" in project.object_paths
    assert "provider-internal/system.bin" in project.object_paths


def test_supabase_migration_blocks_every_direct_operation_on_managed_buckets():
    sql = (Path(__file__).parents[2] / "supabase" / "migrations" /
           "20260831190000_lock_managed_storage_to_backend.sql").read_text(encoding="utf-8")
    assert "as restrictive" in sql.lower()
    for operation in ("select", "insert", "update", "delete"):
        assert f"for {operation}" in sql.lower()
    for bucket in settings.supabase_storage_buckets:
        assert f"'{bucket}'" in sql
