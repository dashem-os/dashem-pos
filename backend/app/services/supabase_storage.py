"""Supabase Storage adapter. Service credentials never leave the backend."""

import re
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services.supabase_credentials import SupabaseCredentialError, supabase_server_headers


class SupabaseStorageUnavailable(RuntimeError):
    pass


class SupabaseStorageRejected(SupabaseStorageUnavailable):
    """A definitive provider-side rejection; no object was accepted."""

    pass


@dataclass(frozen=True)
class StoredObject:
    bucket_id: str
    object_path: str
    provider_reference: str
    size_bytes: int


@dataclass(frozen=True)
class StorageInventory:
    used_bytes: int
    object_count: int
    watermark: str
    object_paths: tuple[str, ...]


def managed_bucket(bucket_id: str) -> str:
    value = bucket_id.strip()
    if value not in settings.supabase_storage_buckets:
        raise ValueError("Bucket não pertence ao namespace gerenciado pelo DASHEM.")
    return value


def tenant_object_path(tenant_id: uuid.UUID, relative_path: str) -> str:
    value = relative_path.strip().strip("/")
    if not value or len(value) > 430 or "\\" in value:
        raise ValueError("Caminho de objeto inválido.")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("Caminho de objeto inválido.")
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]*", segment) for segment in segments):
        raise ValueError("O caminho contém caracteres não permitidos.")
    return f"{tenant_id}/{value}"


def validate_content_signature(content: bytes, content_type: str) -> None:
    """Reject obvious MIME spoofing before consuming provider capacity."""

    valid = True
    if content_type == "image/png":
        valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif content_type == "image/jpeg":
        valid = content.startswith(b"\xff\xd8\xff")
    elif content_type == "image/webp":
        valid = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    elif content_type == "application/pdf":
        valid = content.startswith(b"%PDF-")
    elif content_type == "application/json":
        try:
            json.loads(content)
        except (ValueError, UnicodeDecodeError):
            valid = False
    if not valid:
        raise ValueError("O conteúdo não corresponde ao MIME type declarado.")


def validate_filename_content_type(relative_path: str, content_type: str) -> None:
    """Require a known extension that agrees with the validated MIME type."""

    extension = relative_path.rsplit("/", 1)[-1].lower().rsplit(".", 1)
    suffix = f".{extension[1]}" if len(extension) == 2 else ""
    compatible = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
        "application/pdf": {".pdf"},
        "application/json": {".json"},
        "text/csv": {".csv"},
    }
    if suffix not in compatible.get(content_type, set()):
        raise ValueError("A extensão do arquivo não corresponde ao MIME type declarado.")


class SupabaseStorageClient:
    def __init__(self, client: httpx.Client | None = None):
        if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
            raise SupabaseStorageUnavailable("Supabase Storage não está configurado no backend.")
        self._client = client or httpx.Client(timeout=30.0)
        self._base = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1"
        try:
            self._headers = supabase_server_headers()
        except SupabaseCredentialError as exc:
            raise SupabaseStorageUnavailable(str(exc)) from exc

    def _json(self, response: httpx.Response, message: str) -> Any:
        if response.is_error:
            try:
                detail = response.json().get("message") or response.json().get("error")
            except (ValueError, AttributeError):
                detail = None
            error_type = SupabaseStorageRejected if 400 <= response.status_code < 500 else SupabaseStorageUnavailable
            raise error_type(detail or message)
        return response.json() if response.content else {}

    def ensure_private_buckets(self) -> list[str]:
        response = self._client.get(f"{self._base}/bucket", headers=self._headers)
        existing = {str(item["id"]): item for item in self._json(response, "Falha ao listar buckets.")}
        ready: list[str] = []
        for bucket_id in settings.supabase_storage_buckets:
            current = existing.get(bucket_id)
            if current is None:
                created = self._client.post(
                    f"{self._base}/bucket",
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={
                        "id": bucket_id, "name": bucket_id, "public": False,
                        "file_size_limit": settings.STORAGE_MAX_UPLOAD_BYTES,
                    },
                )
                self._json(created, f"Falha ao criar o bucket privado {bucket_id}.")
            elif current.get("public") is True:
                raise SupabaseStorageUnavailable(f"O bucket {bucket_id} é público e foi recusado.")
            ready.append(bucket_id)
        return ready

    def _list_buckets(self) -> list[dict[str, Any]]:
        response = self._client.get(f"{self._base}/bucket", headers=self._headers)
        return list(self._json(response, "Falha ao listar buckets."))

    def inventory(self, bucket_id: str, prefix: str = "") -> StorageInventory:
        """Exhaustively walk one Storage prefix using provider-owned metadata."""

        bucket = bucket_id.strip()
        if not bucket:
            raise ValueError("Bucket inválido para inventário.")
        pending = [prefix.strip("/")]
        visited: set[str] = set()
        paths: list[str] = []
        used_bytes = 0
        latest: datetime | None = None
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            offset = 0
            while True:
                response = self._client.post(
                    f"{self._base}/object/list/{quote(bucket, safe='')}",
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={
                        "prefix": current, "limit": 1000, "offset": offset,
                        "sortBy": {"column": "name", "order": "asc"},
                    },
                )
                rows = list(self._json(response, f"Falha ao inventariar o bucket {bucket}."))
                for row in rows:
                    name = str(row.get("name") or "").strip("/")
                    if not name:
                        continue
                    full_path = name if not current or name.startswith(f"{current}/") else f"{current}/{name}"
                    metadata = row.get("metadata") or {}
                    object_id = row.get("id")
                    if object_id is None and not metadata:
                        pending.append(full_path)
                        continue
                    try:
                        size = int(metadata.get("size", 0))
                    except (TypeError, ValueError) as exc:
                        raise SupabaseStorageUnavailable(
                            f"O objeto {bucket}/{full_path} não possui tamanho confiável."
                        ) from exc
                    if size < 0:
                        raise SupabaseStorageUnavailable(
                            f"O objeto {bucket}/{full_path} possui tamanho inválido."
                        )
                    used_bytes += size
                    paths.append(full_path)
                    updated = row.get("updated_at") or row.get("updatedAt")
                    if updated:
                        parsed = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        if latest is None or parsed > latest:
                            latest = parsed
                if len(rows) < 1000:
                    break
                offset += len(rows)
        return StorageInventory(
            used_bytes=used_bytes, object_count=len(paths),
            watermark=latest.isoformat() if latest else "EMPTY",
            object_paths=tuple(sorted(paths)),
        )

    def project_inventory(self) -> tuple[StorageInventory, tuple[str, ...]]:
        """Count all buckets because provider capacity is shared project-wide."""

        buckets = tuple(sorted(str(item["id"]) for item in self._list_buckets()))
        snapshots = [self.inventory(bucket) for bucket in buckets]
        paths = tuple(
            f"{bucket}/{path}"
            for bucket, snapshot in zip(buckets, snapshots)
            for path in snapshot.object_paths
        )
        watermarks = sorted(snapshot.watermark for snapshot in snapshots if snapshot.watermark != "EMPTY")
        return StorageInventory(
            used_bytes=sum(snapshot.used_bytes for snapshot in snapshots),
            object_count=sum(snapshot.object_count for snapshot in snapshots),
            watermark=watermarks[-1] if watermarks else "EMPTY",
            object_paths=paths,
        ), buckets

    def upload(self, bucket_id: str, object_path: str, content: bytes, content_type: str) -> StoredObject:
        bucket = managed_bucket(bucket_id)
        encoded = quote(object_path, safe="/")
        response = self._client.post(
            f"{self._base}/object/{bucket}/{encoded}",
            headers={**self._headers, "Content-Type": content_type, "x-upsert": "false"},
            content=content,
        )
        payload = self._json(response, "O Supabase recusou o upload.")
        reference = str(payload.get("Key") or payload.get("key") or payload.get("Id") or object_path)
        return StoredObject(bucket, object_path, reference, len(content))

    def delete(self, bucket_id: str, object_path: str) -> None:
        bucket = managed_bucket(bucket_id)
        response = self._client.delete(
            f"{self._base}/object/{bucket}",
            headers={**self._headers, "Content-Type": "application/json"},
            json={"prefixes": [object_path]},
        )
        self._json(response, "O Supabase recusou a exclusão do objeto.")

    def signed_download_url(self, bucket_id: str, object_path: str, expires_in: int = 60) -> str:
        bucket = managed_bucket(bucket_id)
        encoded = quote(object_path, safe="/")
        response = self._client.post(
            f"{self._base}/object/sign/{bucket}/{encoded}",
            headers={**self._headers, "Content-Type": "application/json"},
            json={"expiresIn": expires_in},
        )
        payload = self._json(response, "Não foi possível assinar o download.")
        signed = payload.get("signedURL") or payload.get("signedUrl")
        if not signed:
            raise SupabaseStorageUnavailable("O Supabase não retornou uma URL assinada.")
        return signed if str(signed).startswith("http") else f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1{signed}"
