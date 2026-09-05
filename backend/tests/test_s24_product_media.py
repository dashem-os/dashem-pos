"""S24 — whose picture it is, and what the screen shows when there is none.

Three claims, and the first one is the one that would be expensive to get wrong.

A shopkeeper's photographs belong to the shopkeeper. Not to a neighbour, and not
to DASHEM: `media_assets` is the one tenant table whose row level security
carries no `app.platform_access` clause, so the platform's own escape hatch —
the one every other tenant table honours for governance — does not open here.
The test below sets that flag and still sees nothing.

The library is a shelf, never a fallback. A product with no chosen picture
resolves to nothing at all, and the card draws its initial. If resolution ever
reached into the library on its own, the platform would be deciding what
somebody else's hamburger looks like.

And the old typed address keeps working. Nothing here rewrites or deletes an
`image_url` registered before the media model existed.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.context import TenantContext
from app.core.database import engine
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import MediaAsset, MediaAssetSourceEnum, PlatformMediaAsset, Product
from app.models.identity import Store, Tenant
from app.services import media_service


def _tenant(session: Session, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name=f"{label} {suffix}", slug=f"{label.lower()}-{suffix}")
    session.add(tenant)
    session.flush()
    store = Store(tenant_id=tenant.id, name="Matriz", code=f"{label[:3].upper()}-{suffix}")
    session.add(store)
    session.flush()
    return tenant.id, store.id


def test_s24_a_tenant_photo_is_invisible_to_its_neighbour_and_to_the_platform():
    with Session(engine) as session:
        set_platform_db_context(session)
        mine, mine_store = _tenant(session, "Fotos")
        theirs, _ = _tenant(session, "Vizinho")
        session.commit()

    # The write happens as the tenant, which is the only way it can happen: the
    # policy has no platform clause, so not even the platform may insert here.
    with Session(engine) as session:
        set_tenant_db_context(session, mine, mine_store, None)
        asset = MediaAsset(
            tenant_id=mine, source=MediaAssetSourceEnum.TENANT_UPLOAD.value,
            bucket_id="tenant-assets", object_path="catalog/segredo.png",
            content_type="image/png", size_bytes=1234,
        )
        session.add(asset)
        session.commit()
        asset_id = asset.id

    # The neighbour, scoped as themselves, sees nothing of mine.
    with Session(engine) as session:
        set_tenant_db_context(session, theirs, None, None)
        found = session.exec(select(MediaAsset).where(MediaAsset.id == asset_id)).all()
        assert found == [], "vizinho leu asset de outro tenant"

    # And neither does the platform, which every other tenant table would let in.
    with Session(engine) as session:
        set_platform_db_context(session)
        visible = session.exec(
            text("SELECT count(*) FROM media_assets WHERE id = :asset_id").bindparams(
                asset_id=str(asset_id)
            )
        ).first()
        assert visible[0] == 0, (
            "a escotilha app.platform_access abriu media_assets: a DASHEM está "
            "enxergando a foto do lojista"
        )

    # The policy itself, so a future migration cannot quietly restore the hatch.
    with Session(engine) as session:
        set_platform_db_context(session)
        policy = session.exec(text(
            "SELECT qual FROM pg_policies WHERE tablename = 'media_assets'"
        )).first()
        assert policy is not None, "media_assets ficou sem política de isolamento"
        assert "platform_access" not in str(policy[0]), (
            "a política de media_assets voltou a carregar a cláusula de plataforma"
        )


def test_s24_the_library_is_a_shelf_and_never_a_fallback():
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant_id, store_id = _tenant(session, "Vitrine")
        library = PlatformMediaAsset(
            code=f"lib-{uuid.uuid4().hex[:8]}", name="Hambúrguer artesanal",
            bucket_id="dashem-library", object_path="food/burger.webp",
            content_type="image/webp", suggested_activities=["FOOD_SERVICE"],
            tags=["hamburguer", "lanche"],
        )
        naked = Product(tenant_id=tenant_id, name="Sem foto", sku=f"SF-{uuid.uuid4().hex[:6]}")
        legacy = Product(
            tenant_id=tenant_id, name="Endereço antigo", sku=f"EA-{uuid.uuid4().hex[:6]}",
            image_url="https://exemplo.invalido/foto.png",
        )
        session.add_all([library, naked, legacy])
        session.commit()
        session.refresh(library)
        session.refresh(naked)
        session.refresh(legacy)
        library_id, naked_id, legacy_id = library.id, naked.id, legacy.id

    with Session(engine) as session:
        # As the tenant, because adopting a shelf picture writes a row the
        # platform itself is not allowed to write.
        set_tenant_db_context(session, tenant_id, store_id, None)
        library = session.get(PlatformMediaAsset, library_id)
        naked = session.get(Product, naked_id)
        legacy = session.get(Product, legacy_id)
        context = TenantContext(tenant_id=tenant_id, store_id=store_id, auth_subject="local-auth-bypass")
        resolved = media_service.resolve_product_images(session, context, [naked, legacy])

        # No picture means no picture. The shelf is not consulted.
        assert naked.id not in resolved, (
            "produto sem escolha recebeu imagem: a biblioteca virou fallback"
        )
        # The address someone pasted before the media model still renders.
        assert resolved[legacy.id]["source"] == "LEGACY_URL"
        assert resolved[legacy.id]["url"] == "https://exemplo.invalido/foto.png"

        # Adopting from the shelf copies nothing, which is why it costs the
        # tenant no storage and works without a storage contract.
        adopted = media_service.adopt_library_asset(
            session, context, library_asset=library, actor_id=None,
        )
        session.commit()
        assert adopted.source == MediaAssetSourceEnum.DASHEM_LIBRARY.value
        assert adopted.size_bytes == 0, "escolher da biblioteca consumiu cota do tenant"
        assert adopted.library_asset_id == library.id
        assert adopted.object_path == library.object_path

        # Choosing twice does not pile up rows for the same shelf picture.
        again = media_service.adopt_library_asset(
            session, context, library_asset=library, actor_id=None,
        )
        assert again.id == adopted.id

        # And the legacy address is still exactly where it was.
        session.refresh(legacy)
        assert legacy.image_url == "https://exemplo.invalido/foto.png"


def test_s24_signed_url_lifetime_follows_the_purpose_not_the_caller():
    """A product photo is not a private document, and neither is a shelf image."""
    from app.core.config import settings

    assert media_service._ttl_for("tenant-assets") == settings.CATALOG_MEDIA_SIGNED_URL_TTL_SECONDS
    assert media_service._ttl_for("dashem-library") == settings.LIBRARY_MEDIA_SIGNED_URL_TTL_SECONDS
    assert media_service._ttl_for("tenant-documents") == settings.DOCUMENT_SIGNED_URL_TTL_SECONDS
    # Six hours covers a shift; sixty seconds would expire before a lazily
    # loaded window finished requesting its own pictures.
    assert settings.CATALOG_MEDIA_SIGNED_URL_TTL_SECONDS == 21600
    assert settings.DOCUMENT_SIGNED_URL_TTL_SECONDS == 60
