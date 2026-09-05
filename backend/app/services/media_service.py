"""Resolving a product's picture, in one place and for many products at once.

The chain is deterministic and short:

    chosen asset  →  legacy `image_url`  →  nothing

"Nothing" means the screen draws the product's initial. The DASHEM library is
never consulted here: it is a shelf the shopkeeper picks from, not a fallback
the system reaches into. A product without a chosen picture is a product whose
owner has not chosen one, and inventing an image would be the system deciding
how someone else's item looks.

Signing happens on the server and in bulk. A card that signs its own URL turns a
window of twenty items into twenty round trips, and with the sixty-second life a
document deserves, half of them would expire before a lazily loaded image ever
requested them. Catalogue media lives six hours, so the same signature serves a
whole shift, and the result is cached in-process for the rest of its life minus
a safety margin.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from app.core.config import settings
from app.core.context import TenantContext, scope_tenant_query
from app.models.catalog import MediaAsset, MediaAssetSourceEnum
from app.services.supabase_storage import SupabaseStorageClient, SupabaseStorageUnavailable

# A signature is reused while it still has more than this left to live, so a
# picture never blanks out in the middle of somebody's shift.
_RENEWAL_MARGIN = timedelta(minutes=15)
_signed_cache: dict[tuple[str, str], tuple[str, datetime]] = {}


def _ttl_for(bucket_id: str) -> int:
    if bucket_id == "tenant-assets":
        return settings.CATALOG_MEDIA_SIGNED_URL_TTL_SECONDS
    if bucket_id == "dashem-library":
        return settings.LIBRARY_MEDIA_SIGNED_URL_TTL_SECONDS
    return settings.DOCUMENT_SIGNED_URL_TTL_SECONDS


def _sign(bucket_id: str, object_path: str) -> Optional[tuple[str, datetime]]:
    key = (bucket_id, object_path)
    cached = _signed_cache.get(key)
    now = datetime.utcnow()
    if cached and cached[1] - now > _RENEWAL_MARGIN:
        return cached
    ttl = _ttl_for(bucket_id)
    try:
        url = SupabaseStorageClient().signed_download_url(bucket_id, object_path, expires_in=ttl)
    except (SupabaseStorageUnavailable, Exception):
        # A provider that is down must not empty the catalogue. The card falls
        # back to the initial for this request and tries again on the next one.
        return None
    signed = (url, now + timedelta(seconds=ttl))
    _signed_cache[key] = signed
    return signed


def sign_library_asset(library_asset) -> Optional[tuple[str, datetime]]:
    """A library picture is public to every tenant, and signed for a day."""
    return _sign(library_asset.bucket_id, library_asset.object_path)


def resolve_product_images(
    session: Session, context: TenantContext, products: Iterable[Any],
) -> dict[uuid.UUID, dict[str, Any]]:
    """Map product id → `{source, url, expires_at}` for everything resolvable.

    A product absent from the result has no picture, and the screen says so with
    its initial rather than with a broken frame.
    """
    products = list(products)
    asset_ids = {
        p.primary_media_asset_id for p in products
        if getattr(p, "primary_media_asset_id", None)
    }
    assets: dict[uuid.UUID, MediaAsset] = {}
    if asset_ids:
        assets = {
            asset.id: asset
            for asset in session.exec(
                scope_tenant_query(
                    select(MediaAsset).where(MediaAsset.id.in_(asset_ids)), MediaAsset, context
                )
            ).all()
        }

    resolved: dict[uuid.UUID, dict[str, Any]] = {}
    for product in products:
        asset = assets.get(getattr(product, "primary_media_asset_id", None))
        if asset:
            signed = _sign(asset.bucket_id, asset.object_path)
            if signed:
                resolved[product.id] = {
                    "source": asset.source,
                    "url": signed[0],
                    # Naive UTC on the wire, like every other timestamp here, so
                    # the frontend guard reads it as UTC and not as local time.
                    "expires_at": signed[1].isoformat(),
                }
                continue
        legacy = getattr(product, "image_url", None)
        if legacy:
            # An address somebody pasted before the media model existed. It keeps
            # working, and nothing here rewrites or deletes it.
            resolved[product.id] = {"source": "LEGACY_URL", "url": legacy, "expires_at": None}
    return resolved


def register_tenant_upload(
    session: Session, context: TenantContext, *,
    bucket_id: str, object_path: str, content_type: str, size_bytes: int,
    original_filename: Optional[str], actor_id: Optional[uuid.UUID],
) -> MediaAsset:
    """Record a file the shopkeeper uploaded into their own namespace."""
    existing = session.exec(scope_tenant_query(
        select(MediaAsset).where(
            MediaAsset.bucket_id == bucket_id, MediaAsset.object_path == object_path,
        ), MediaAsset, context,
    )).first()
    if existing:
        return existing
    asset = MediaAsset(
        tenant_id=context.tenant_id, source=MediaAssetSourceEnum.TENANT_UPLOAD.value,
        bucket_id=bucket_id, object_path=object_path, content_type=content_type,
        size_bytes=size_bytes, original_filename=original_filename, created_by=actor_id,
    )
    session.add(asset)
    session.flush()
    return asset


def adopt_library_asset(
    session: Session, context: TenantContext, *, library_asset, actor_id: Optional[uuid.UUID],
) -> MediaAsset:
    """Point a tenant at a library picture without copying a single byte.

    Choosing from the shelf costs the tenant no storage, which is why a tenant
    with no storage contract still has a window with pictures.
    """
    existing = session.exec(scope_tenant_query(
        select(MediaAsset).where(MediaAsset.library_asset_id == library_asset.id),
        MediaAsset, context,
    )).first()
    if existing:
        return existing
    asset = MediaAsset(
        tenant_id=context.tenant_id, source=MediaAssetSourceEnum.DASHEM_LIBRARY.value,
        bucket_id=library_asset.bucket_id, object_path=library_asset.object_path,
        content_type=library_asset.content_type, size_bytes=0,
        original_filename=library_asset.name, library_asset_id=library_asset.id,
        created_by=actor_id,
    )
    session.add(asset)
    session.flush()
    return asset
