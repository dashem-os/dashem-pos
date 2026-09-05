"""Exercise real API serialization and database constraints behind catalog editing."""
import uuid
from decimal import Decimal
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.main import app
from app.core.config import settings
from app.core.context import TenantContext, get_tenant_context
from app.core.database import engine, get_session
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.models.catalog import Product, ProductPrice, InventoryBalance, InventoryMovement, MediaAsset
from app.models.identity import Tenant, Store, User
from app.models.storage import StorageMeasurement, StorageMeterSource
from app.services import media_service, storage_quota_service
from app.services.catalog_storage_service import prepare_catalog_storage
from app.services.supabase_storage import StorageInventory, SupabaseStorageUnavailable


@pytest.fixture
def catalog():
    suffix = uuid.uuid4().hex
    with Session(engine) as session:
        set_platform_db_context(session)
        tenant = Tenant(name='Catalog test', slug=f'cat-{suffix}')
        user = User(full_name='Catalog editor', email=f'{suffix}@example.test')
        session.add_all([tenant, user]); session.flush()
        store = Store(tenant_id=tenant.id, name='Matriz', code=f'S-{suffix}')
        other = Tenant(name='Other tenant', slug=f'other-{suffix}')
        session.add_all([store, other]); session.commit()
        context = TenantContext(tenant_id=tenant.id, store_id=store.id, user_id=user.id, permissions=('management.read', 'catalog.update'))
        other_id = other.id

    def scoped_session():
        with Session(engine) as session:
            set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
            yield session

    app.dependency_overrides[get_tenant_context] = lambda: context
    app.dependency_overrides[get_session] = scoped_session
    try:
        with TestClient(app) as client:
            yield client, context, other_id
    finally:
        app.dependency_overrides.pop(get_tenant_context, None)
        app.dependency_overrides.pop(get_session, None)


def test_edit_price_and_photo_survive_the_http_response(catalog, monkeypatch):
    client, context, _ = catalog
    product = client.post('/api/v1/catalog/products', json={'name': 'Hambúrguer', 'sku': 'HAB-01'}).json()
    product_id = product['id']
    price = client.post('/api/v1/catalog/prices', json={
        'product_id': product_id, 'store_id': str(context.store_id), 'sale_price': 32, 'cost_price': 12,
    })
    assert price.status_code == 200
    result = client.patch(f'/api/v1/catalog/products/{product_id}', json={'name': 'Hambúrguer bacon', 'sale_price': '1234.56', 'barcode': None})
    assert result.status_code == 200, result.text
    monkeypatch.setattr(media_service, '_sign', lambda *args: ('https://example.test/signed-photo', datetime.utcnow() + timedelta(hours=6)))
    photo = client.put(f'/api/v1/catalog/products/{product_id}/media', json={
        'bucket_id': 'tenant-assets', 'object_path': f'{context.tenant_id}/catalog/photo.png',
        'content_type': 'image/png', 'size_bytes': 20,
    })
    assert photo.status_code == 200, photo.text
    page = client.get('/api/v1/catalog/sellable-products?master=true').json()
    assert 'items' in page, page
    item = page['items'][0]
    assert item['name'] == 'Hambúrguer bacon'
    assert Decimal(str(item['sale_price'])) == Decimal('1234.56')
    assert Decimal(str(item['cost_price'])) == Decimal('12')
    assert item['image']['url'] == 'https://example.test/signed-photo'
    assert client.put(f'/api/v1/catalog/products/{product_id}/media', json={'clear': True}).status_code == 200
    assert client.get('/api/v1/catalog/sellable-products?master=true').json()['items'][0]['image'] is None


def test_delete_unused_registration_preserves_media_and_rejects_history_and_other_tenant(catalog):
    client, context, other_id = catalog
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        asset = MediaAsset(tenant_id=context.tenant_id, bucket_id='tenant-assets', object_path=f'{context.tenant_id}/photo.png', content_type='image/png', size_bytes=20, source='TENANT_UPLOAD')
        session.add(asset); session.flush()
        product = Product(tenant_id=context.tenant_id, name='Unused', sku='unused', primary_media_asset_id=asset.id)
        used = Product(tenant_id=context.tenant_id, name='Used', sku='used')
        session.add_all([product, used]); session.flush()
        session.add(ProductPrice(tenant_id=context.tenant_id, store_id=context.store_id, product_id=product.id, sale_price=32))
        session.add(InventoryBalance(tenant_id=context.tenant_id, store_id=context.store_id, product_id=product.id, quantity=0))
        session.add(InventoryMovement(tenant_id=context.tenant_id, store_id=context.store_id, product_id=used.id, actor_id=context.user_id, quantity=1, previous_balance=0, new_balance=1))
        session.commit()
        product_id, used_id, asset_id = product.id, used.id, asset.id
    assert client.delete(f'/api/v1/catalog/products/{used_id}/permanent').status_code == 409
    assert client.delete(f'/api/v1/catalog/products/{product_id}/permanent').status_code == 204
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        assert session.get(Product, product_id) is None
        assert session.get(MediaAsset, asset_id) is not None
        assert session.get(Product, used_id) is not None
        set_tenant_db_context(session, other_id)
        other = Product(tenant_id=other_id, name='Other', sku='other')
        session.add(other); session.commit()
        other_product_id = other.id
    assert client.delete(f'/api/v1/catalog/products/{other_product_id}/permanent').status_code == 404


def test_prepare_measures_provider_and_preserves_request_isolation(catalog, monkeypatch):
    _, context, other_id = catalog
    monkeypatch.setattr(settings, 'SUPABASE_URL', 'https://example.test')
    monkeypatch.setattr(settings, 'SUPABASE_SECRET_KEY', 'test-only')
    monkeypatch.setattr(settings, 'SUPABASE_STORAGE_CAPACITY_BYTES', 1_000_000_000)
    monkeypatch.setattr(storage_quota_service, '_contracted_storage_bytes', lambda *a: 1024 * 1024)
    from app.services import catalog_storage_service
    calls = []

    class Provider:
        def ensure_private_buckets(self):
            calls.append('private-buckets')
        def inventory(self, bucket, prefix):
            assert prefix == str(context.tenant_id)
            return StorageInventory(used_bytes=20, object_count=1, watermark='TEST', object_paths=(f'{prefix}/photo.png',))
        def project_inventory(self):
            return StorageInventory(used_bytes=80, object_count=4, watermark='TEST', object_paths=()), tuple(settings.supabase_storage_buckets)

    monkeypatch.setattr(catalog_storage_service, 'SupabaseStorageClient', Provider)
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        result = prepare_catalog_storage(session, context)
        assert result['upload_available'] is True, str(result)
        assert result['used_bytes'] == 80
        assert session.exec(text("select current_setting('app.platform_access')")).first()[0] == 'false'
        assert session.get(Tenant, other_id) is None
        assert len(session.exec(select(StorageMeterSource)).all()) == 4
        assert len(session.exec(select(StorageMeasurement)).all()) == 1
        assert prepare_catalog_storage(session, context)['upload_available'] is True
        assert calls == ['private-buckets']


def test_prepare_does_not_invent_capacity_when_provider_is_missing(catalog, monkeypatch):
    _, context, _ = catalog
    monkeypatch.setattr(settings, 'SUPABASE_STORAGE_CAPACITY_BYTES', None)
    with Session(engine) as session:
        set_tenant_db_context(session, context.tenant_id, context.store_id, context.user_id)
        with pytest.raises(SupabaseStorageUnavailable):
            prepare_catalog_storage(session, context)
        assert session.exec(select(StorageMeasurement)).all() == []
