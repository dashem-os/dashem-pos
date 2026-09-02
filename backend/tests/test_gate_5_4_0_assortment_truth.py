import asyncio
import os
import uuid
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.database import engine
from app.core.context import TenantContext, authorize_tenant_context, resolve_actor
from app.core.security import AuthPrincipal
from app.core.tenancy import set_platform_db_context, set_tenant_db_context
from app.services import catalog_service
from app.models.assortment import Assortment, AssortmentScope, AssortmentProduct, SalesContextEnum
from app.models.catalog import Product
from app.models.channel import SalesChannel, SalesChannelTypeEnum
from app.models.identity import Tenant, Store, User, Membership, RoleEnum
from app.models.platform import TenantCapability, EntitlementStatusEnum
from app.models.reliability import OutboxEvent

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


def test_master_catalog_requires_management_authority():
    """The master catalog flag cannot be used as an operational publication bypass."""
    context = TenantContext(
        tenant_id=uuid.uuid4(),
        store_id=uuid.uuid4(),
        permissions=("catalog.read",),
        auth_subject="authenticated-user",
    )
    with pytest.raises(HTTPException) as exc_info:
        catalog_service.list_sellable_products(
            Session(engine), context, page=1, page_size=25, search=None,
            category_id=None, quick_access=False, master=True,
        )
    assert exc_info.value.status_code == 403


def test_local_bypass_does_not_invent_contract_capabilities():
    """A disabled-auth test context must reflect the persisted contract exactly."""
    tenant_id, store_id = uuid.uuid4(), uuid.uuid4()
    principal = AuthPrincipal(
        subject="local-auth-bypass", email=None, session_id=None,
        assurance_level="aal1", claims={}, provider="local", bypass=True,
    )
    with Session(engine) as session:
        context = authorize_tenant_context(
            session, principal, tenant_id, store_id, "GET", "/api/v1/catalog/sellable-products",
        )
        assert context.capabilities == ()


def test_authenticated_actor_resolution_rejects_spoofing():
    """The service-level identity boundary is independent of local auth mode."""
    user_id = uuid.uuid4()
    context = TenantContext(tenant_id=uuid.uuid4(), user_id=user_id, auth_subject="supabase-subject")
    assert resolve_actor(context) == user_id
    assert resolve_actor(context, user_id) == user_id
    with pytest.raises(HTTPException) as exc_info:
        resolve_actor(context, uuid.uuid4())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_new_tenant_without_assortments_has_no_fallback_on_order_add_item():
    """
    Blocker 1 & Core Requirement:
    A new tenant without assortments must NEVER fall back silently to the master catalog.
    Querying sellable-products returns empty, and adding any product to an order is rejected with HTTP 400.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={
            "name": f"New Tenant {suffix}", "slug": f"new-tenant-{suffix}"
        })).json()
        store = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Matriz", "code": f"M-{suffix}"
        })).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        # Create master product with price and stock
        prod = (await client.post("/api/v1/catalog/products", headers=headers, json={
            "name": "Produto Sem Sortimento", "sku": f"SEM-SORT-{suffix}", "unit": "UN",
        })).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={
            "product_id": prod["id"], "store_id": store["id"], "cost_price": 10, "sale_price": 25,
        })

        # 1. sellable-products for COUNTER must return empty list (no silent fallback)
        sellable = (await client.get("/api/v1/catalog/sellable-products?sales_context=COUNTER", headers=headers)).json()
        assert sellable["total"] == 0
        assert len(sellable["items"]) == 0

        # 2. create order
        actor_id = str(uuid.uuid4())
        order = (await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": f"ord-new-{suffix}"}, json={
            "store_id": store["id"], "origin": "POS", "fulfillment": "COUNTER",
            "actor_id": actor_id,
        })).json()

        # 3. add_item MUST fail with 400 because product is not in an authorized assortment
        add_res = await client.post(
            f"/api/v1/orders/{order['id']}/items",
            headers={**headers, "Idempotency-Key": f"item-new-{suffix}"},
            json={"product_id": prod["id"], "quantity": 1, "actor_id": actor_id},
        )
        assert add_res.status_code == 400
        assert "não pertence ao sortimento autorizado para o contexto COUNTER" in add_res.json()["detail"]


@pytest.mark.asyncio
async def test_two_stores_same_tenant_independent_assortment_scopes():
    """
    Two stores of the SAME tenant must have independent assortment scopes.
    Products in Store 1's assortment must not appear or be orderable in Store 2.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={
            "name": f"Multi Store {suffix}", "slug": f"multi-store-{suffix}"
        })).json()
        store1 = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Loja 1", "code": f"L1-{suffix}"
        })).json()
        store2 = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Loja 2", "code": f"L2-{suffix}"
        })).json()
        h1 = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store1["id"]}
        h2 = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store2["id"]}

        # Master products
        p1 = (await client.post("/api/v1/catalog/products", headers=h1, json={"name": "Prod Loja 1", "sku": f"P1-{suffix}"})).json()
        p2 = (await client.post("/api/v1/catalog/products", headers=h2, json={"name": "Prod Loja 2", "sku": f"P2-{suffix}"})).json()
        await client.post("/api/v1/catalog/prices", headers=h1, json={"product_id": p1["id"], "store_id": store1["id"], "cost_price": 5, "sale_price": 10})
        await client.post("/api/v1/catalog/prices", headers=h2, json={"product_id": p2["id"], "store_id": store2["id"], "cost_price": 5, "sale_price": 10})

        # Assortment 1: strictly scoped to Store 1, COUNTER
        await client.post("/api/v1/catalog/assortments", headers=h1, json={
            "code": f"ASSORT-S1-{suffix}",
            "name": "Sortimento Loja 1",
            "scopes": [{"store_id": store1["id"], "sales_context": "COUNTER"}],
            "product_ids": [p1["id"]],
        })

        # Assortment 2: strictly scoped to Store 2, COUNTER
        await client.post("/api/v1/catalog/assortments", headers=h2, json={
            "code": f"ASSORT-S2-{suffix}",
            "name": "Sortimento Loja 2",
            "scopes": [{"store_id": store2["id"], "sales_context": "COUNTER"}],
            "product_ids": [p2["id"]],
        })

        # Query Store 1: contains p1, but NOT p2
        s1_items = (await client.get("/api/v1/catalog/sellable-products?sales_context=COUNTER", headers=h1)).json()["items"]
        s1_ids = {item["id"] for item in s1_items}
        assert p1["id"] in s1_ids
        assert p2["id"] not in s1_ids

        # Query Store 2: contains p2, but NOT p1
        s2_items = (await client.get("/api/v1/catalog/sellable-products?sales_context=COUNTER", headers=h2)).json()["items"]
        s2_ids = {item["id"] for item in s2_items}
        assert p2["id"] in s2_ids
        assert p1["id"] not in s2_ids

        # Order in Store 1 cannot add p2
        actor_id = str(uuid.uuid4())
        ord1 = (await client.post("/api/v1/orders", headers={**h1, "Idempotency-Key": f"ord1-{suffix}"}, json={
            "store_id": store1["id"], "origin": "POS", "fulfillment": "COUNTER", "actor_id": actor_id,
        })).json()
        reject_p2 = await client.post(f"/api/v1/orders/{ord1['id']}/items", headers={**h1, "Idempotency-Key": f"ord1-p2-{suffix}"}, json={
            "product_id": p2["id"], "quantity": 1, "actor_id": actor_id,
        })
        assert reject_p2.status_code == 400


@pytest.mark.asyncio
async def test_missing_capabilities_rejected_on_catalog_and_orders():
    """
    Capabilities govern journey access.
    - Without table_service, TABLE context is rejected on catalog and order creation with 403.
    - Without delivery_orders, DELIVERY context is rejected on catalog and order creation with 403.
    - ECOMMERCE journey is rejected with 403.
    - Once capability is granted, access succeeds.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={
            "name": f"Cap Tenant {suffix}", "slug": f"cap-{suffix}"
        })).json()
        store = (await client.post("/api/v1/identity/stores", json={
            "tenant_id": tenant["id"], "name": "Matriz", "code": f"CAP-{suffix}"
        })).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        # 1. ECOMMERCE is not contracted -> 403
        ecom_cat = await client.get("/api/v1/catalog/sellable-products?sales_context=ECOMMERCE", headers=headers)
        assert ecom_cat.status_code == 403
        assert "e-commerce não contratada" in ecom_cat.json()["detail"]

        # 2. TABLE context without table_service capability -> 403 on catalog and order
        table_cat = await client.get("/api/v1/catalog/sellable-products?sales_context=TABLE", headers=headers)
        assert table_cat.status_code == 403
        assert "table_service" in table_cat.json()["detail"]

        table_ord = await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": f"ord-tbl-{suffix}"}, json={
            "store_id": store["id"], "origin": "POS", "fulfillment": "DINE_IN",
        })
        assert table_ord.status_code == 403
        assert "table_service" in table_ord.json()["detail"]

        # 3. DELIVERY context without delivery_orders capability -> 403 on catalog and order
        deliv_cat = await client.get("/api/v1/catalog/sellable-products?sales_context=DELIVERY", headers=headers)
        assert deliv_cat.status_code == 403
        assert "delivery_orders" in deliv_cat.json()["detail"]

        deliv_ord = await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": f"ord-del-{suffix}"}, json={
            "store_id": store["id"], "origin": "POS", "fulfillment": "DELIVERY",
        })
        assert deliv_ord.status_code == 403
        assert "delivery_orders" in deliv_ord.json()["detail"]

        # 4. Context bypass (missing context) -> 400
        no_ctx = await client.get("/api/v1/catalog/sellable-products", headers=headers)
        assert no_ctx.status_code == 400

        # 5. Missing store header -> 400
        no_store = await client.get("/api/v1/catalog/sellable-products?sales_context=COUNTER", headers={"X-Tenant-ID": tenant["id"]})
        assert no_store.status_code == 400

        # 6. Once table_service is granted, TABLE journey succeeds
        with Session(engine) as db:
            set_platform_db_context(db)
            db.add(TenantCapability(
                tenant_id=uuid.UUID(tenant["id"]),
                key="table_service",
                enabled=True,
                status=EntitlementStatusEnum.ACTIVE,
            ))
            db.commit()

        # Catalog query for TABLE succeeds (empty items, no assortment yet)
        table_cat_ok = await client.get("/api/v1/catalog/sellable-products?sales_context=TABLE", headers=headers)
        assert table_cat_ok.status_code == 200
        assert table_cat_ok.json()["items"] == []

        # Order creation for DINE_IN succeeds
        table_ord_ok = await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": f"ord-tbl-ok-{suffix}"}, json={
            "store_id": store["id"], "origin": "POS", "fulfillment": "DINE_IN",
        })
        assert table_ord_ok.status_code in {200, 201}


@pytest.mark.asyncio
async def test_real_concurrent_race_condition_on_assortment_version():
    """
    Blocker 3: Atomic optimistic concurrency.
    Two simultaneous requests trying to update or link products with the same expected_version.
    Exactly one must succeed, and the other must receive HTTP 409 Conflict.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Race {suffix}", "slug": f"race-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"R-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        # Create assortment at version 1
        assortment = (await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-RACE-{suffix}",
            "name": "Sortimento Concorrência",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
            "product_ids": [],
        })).json()
        assert assortment["version"] == 1

        # Fire two concurrent update requests with expected_version=1
        async def do_update(name_suffix: str):
            async with httpx.AsyncClient(base_url=BASE_URL) as cl:
                return await cl.patch(
                    f"/api/v1/catalog/assortments/{assortment['id']}",
                    headers={**headers, "Idempotency-Key": f"race-up-{name_suffix}-{suffix}"},
                    json={"expected_version": 1, "name": f"Nome {name_suffix}"},
                )

        r1, r2 = await asyncio.gather(do_update("A"), do_update("B"))
        statuses = {r1.status_code, r2.status_code}
        assert statuses == {200, 409}, f"Expected one 200 and one 409, got: {r1.status_code} and {r2.status_code}"

        # Current version in DB must be exactly 2
        fresh = (await client.get(f"/api/v1/catalog/assortments/{assortment['id']}", headers=headers)).json()
        assert fresh["version"] == 2


@pytest.mark.asyncio
async def test_channel_id_scope_preservation():
    """
    Blocker 4: Scopes bound to a specific channel_id must be preserved across updates
    and correctly filter products when queried with or without channel_id.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Chan {suffix}", "slug": f"chan-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"CH-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        # Create a channel directly in DB
        with Session(engine) as db:
            set_platform_db_context(db)
            channel = SalesChannel(
                tenant_id=uuid.UUID(tenant["id"]),
                name=f"Canal Especial {suffix}",
                code=f"CH-ESP-{suffix}",
                channel_type=SalesChannelTypeEnum.OTHER,
                is_active=True,
            )
            db.add(channel)
            db.commit()
            db.refresh(channel)
            channel_id = str(channel.id)

        prod = (await client.post("/api/v1/catalog/products", headers=headers, json={"name": "Canal Exclusivo", "sku": f"CEX-{suffix}"})).json()
        await client.post("/api/v1/catalog/prices", headers=headers, json={"product_id": prod["id"], "store_id": store["id"], "cost_price": 5, "sale_price": 20})

        # Create assortment with explicit channel_id scope
        assortment = (await client.post("/api/v1/catalog/assortments", headers=headers, json={
            "code": f"ASSORT-CH-{suffix}",
            "name": "Cardápio do Canal",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER", "channel_id": channel_id}],
            "product_ids": [prod["id"]],
        })).json()
        assert assortment["scopes"][0]["channel_id"] == channel_id

        # Update assortment (change description) and ensure channel_id is NOT destroyed
        updated = (await client.patch(f"/api/v1/catalog/assortments/{assortment['id']}", headers=headers, json={
            "expected_version": 1,
            "description": "Descrição atualizada",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER", "channel_id": channel_id}],
        })).json()
        assert updated["scopes"][0]["channel_id"] == channel_id

        # Query sellable products WITH matching channel_id -> product is present
        with_channel = (await client.get(f"/api/v1/catalog/sellable-products?sales_context=COUNTER&channel_id={channel_id}", headers=headers)).json()
        assert with_channel["total"] == 1
        assert with_channel["items"][0]["id"] == prod["id"]

        # Query sellable products with a DIFFERENT channel_id -> product is NOT present
        other_ch = str(uuid.uuid4())
        diff_channel = (await client.get(f"/api/v1/catalog/sellable-products?sales_context=COUNTER&channel_id={other_ch}", headers=headers)).json()
        assert diff_channel["total"] == 0


def test_rls_using_runtime_role_directly():
    """
    Direct verification of Row Level Security using non-owner runtime role `dashem_runtime`.
    `dashem_runtime` has rolsuper=False, rolbypassrls=False.
    RLS strictly isolates rows by tenant_id = current_setting('app.tenant_id').
    Tenant B cannot see Tenant A's assortments, and cross-tenant inserts fail.
    """
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    assort_id = uuid.uuid4()
    store_a_id = uuid.uuid4()
    product_a_id = uuid.uuid4()
    product_a2_id = uuid.uuid4()
    scope_a_id = uuid.uuid4()
    link_a_id = uuid.uuid4()

    # Step 1: Create tenant records under platform context
    with Session(engine) as session:
        set_platform_db_context(session)
        t_a = Tenant(id=tenant_a_id, name=f"RLS Tenant A {uuid.uuid4().hex[:6]}", slug=f"rls-a-{uuid.uuid4().hex[:6]}")
        t_b = Tenant(id=tenant_b_id, name=f"RLS Tenant B {uuid.uuid4().hex[:6]}", slug=f"rls-b-{uuid.uuid4().hex[:6]}")
        session.add(t_a)
        session.add(t_b)
        session.add(Store(id=store_a_id, tenant_id=tenant_a_id, name="RLS Store A", code=f"RLS-{uuid.uuid4().hex[:6]}"))
        session.add(Product(id=product_a_id, tenant_id=tenant_a_id, name="RLS Product A", sku=f"RLS-{uuid.uuid4().hex[:6]}"))
        session.add(Product(id=product_a2_id, tenant_id=tenant_a_id, name="RLS Product A2", sku=f"RLS-{uuid.uuid4().hex[:6]}"))
        session.commit()

    # Step 2: Test as non-owner runtime role `dashem_runtime`
    with engine.connect() as conn:
        conn.execute(text("SET ROLE dashem_runtime;"))
        try:
            # Confirm current_user is dashem_runtime (rolbypassrls = False)
            current_user = conn.execute(text("SELECT current_user;")).scalar()
            assert current_user == "dashem_runtime"

            # Set tenant A context
            conn.execute(text("SELECT set_config('app.platform_access', 'false', false);"))
            conn.execute(text("SELECT set_config('app.tenant_id', :tid, false);"), {"tid": str(tenant_a_id)})

            # Insert an assortment under Tenant A
            conn.execute(text("""
                INSERT INTO assortments (id, tenant_id, code, name, status, version, created_at, updated_at)
                VALUES (:id, :tenant_id, :code, :name, 'ACTIVE', 1, now(), now());
            """), {
                "id": str(assort_id),
                "tenant_id": str(tenant_a_id),
                "code": f"RLS-A-{uuid.uuid4().hex[:6]}",
                "name": "Sortimento RLS Runtime",
            })
            conn.commit()

            # Related rows must be visible under the same tenant context.
            conn.execute(text("""
                INSERT INTO assortment_scopes
                    (id, tenant_id, assortment_id, store_id, sales_context, created_at)
                VALUES (:id, :tenant_id, :assortment_id, :store_id, 'COUNTER', now());
            """), {
                "id": str(scope_a_id), "tenant_id": str(tenant_a_id),
                "assortment_id": str(assort_id), "store_id": str(store_a_id),
            })
            conn.execute(text("""
                INSERT INTO assortment_products
                    (id, tenant_id, assortment_id, product_id, sort_order, created_at)
                VALUES (:id, :tenant_id, :assortment_id, :product_id, 100, now());
            """), {
                "id": str(link_a_id), "tenant_id": str(tenant_a_id),
                "assortment_id": str(assort_id), "product_id": str(product_a_id),
            })
            conn.commit()

            # Select as Tenant A -> exactly 1 row returned
            rows_a = conn.execute(text("SELECT id FROM assortments WHERE id = :id;"), {"id": str(assort_id)}).fetchall()
            assert len(rows_a) == 1

            # Switch context to Tenant B
            conn.execute(text("SELECT set_config('app.tenant_id', :tid, false);"), {"tid": str(tenant_b_id)})

            # Select as Tenant B -> 0 rows returned (RLS isolation enforced)
            rows_b = conn.execute(text("SELECT id FROM assortments WHERE id = :id;"), {"id": str(assort_id)}).fetchall()
            assert len(rows_b) == 0
            assert not conn.execute(text("SELECT id FROM assortment_scopes WHERE id = :id;"), {"id": str(scope_a_id)}).fetchall()
            assert not conn.execute(text("SELECT id FROM assortment_products WHERE id = :id;"), {"id": str(link_a_id)}).fetchall()

            # Direct select on assortments for Tenant B returns 0
            all_b = conn.execute(text("SELECT id FROM assortments WHERE tenant_id = :tid;"), {"tid": str(tenant_a_id)}).fetchall()
            assert len(all_b) == 0

            # Attempting cross-tenant insert under Tenant B context for Tenant A violates RLS WITH CHECK policy
            cross_tenant_insert_failed = False
            try:
                conn.execute(text("""
                    INSERT INTO assortments (id, tenant_id, code, name, status, version, created_at, updated_at)
                    VALUES (:id, :tenant_id, :code, :name, 'ACTIVE', 1, now(), now());
                """), {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_a_id),
                    "code": f"RLS-CROSS-{uuid.uuid4().hex[:6]}",
                    "name": "Cross Tenant Attempt",
                })
                conn.commit()
            except Exception as exc:
                cross_tenant_insert_failed = True
                conn.rollback()
                assert "violates row-level security policy" in str(exc) or "insufficient_privilege" in str(exc).lower()
            assert cross_tenant_insert_failed, "Cross-tenant INSERT under dashem_runtime must be blocked by RLS"

            # The same WITH CHECK boundary must apply to the related tables.
            for table, columns, values in (
                (
                    "assortment_scopes",
                    "id, tenant_id, assortment_id, store_id, sales_context, created_at",
                    f"'{uuid.uuid4()}', '{tenant_a_id}', '{assort_id}', '{store_a_id}', 'DELIVERY', now()",
                ),
                (
                    "assortment_products",
                    "id, tenant_id, assortment_id, product_id, sort_order, created_at",
                    f"'{uuid.uuid4()}', '{tenant_a_id}', '{assort_id}', '{product_a2_id}', 100, now()",
                ),
            ):
                # A failed statement rolls back the transaction-local GUC
                # state on this connection. Re-assert Tenant B before each
                # related-table probe so the check cannot silently run with
                # Tenant A's previous context.
                conn.execute(text("SELECT set_config('app.platform_access', 'false', false);"))
                conn.execute(text("SELECT set_config('app.tenant_id', :tid, false);"), {"tid": str(tenant_b_id)})
                failed = False
                try:
                    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values});"))
                    conn.commit()
                except Exception as exc:
                    failed = True
                    conn.rollback()
                    assert "violates row-level security policy" in str(exc) or "insufficient_privilege" in str(exc).lower()
                assert failed, f"Cross-tenant INSERT into {table} must be blocked by RLS"

        finally:
            conn.execute(text("RESET ROLE;"))
            conn.commit()


@pytest.mark.asyncio
async def test_idempotency_atomicity_and_recovery():
    """
    Blocker 6: Idempotent mutations are committed atomically with the mutation.
    Re-submitting the same Idempotency-Key replays the exact response.
    Re-submitting with modified payload raises HTTP 409 Conflict.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Idem {suffix}", "slug": f"idem-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"ID-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        idem_key = f"key-{suffix}"
        payload = {
            "code": f"ASSORT-IDEM-{suffix}",
            "name": "Sortimento Idempotente",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
            "product_ids": [],
        }

        # First call: 201 Created
        res1 = await client.post("/api/v1/catalog/assortments", headers={**headers, "Idempotency-Key": idem_key}, json=payload)
        assert res1.status_code == 201
        data1 = res1.json()

        # Replay same key & payload: returns same record with version 1
        res2 = await client.post("/api/v1/catalog/assortments", headers={**headers, "Idempotency-Key": idem_key}, json=payload)
        assert res2.status_code in {200, 201}
        data2 = res2.json()
        assert data1["id"] == data2["id"]
        assert data2["version"] == 1

        # Replay same key with DIFFERENT payload: 409 Conflict
        res3 = await client.post(
            "/api/v1/catalog/assortments",
            headers={**headers, "Idempotency-Key": idem_key},
            json={**payload, "name": "Nome Alterado"},
        )
        assert res3.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_idempotent_assortment_creation():
    """
    Two concurrent requests sending the identical Idempotency-Key and payload.
    Both must resolve without unhandled crashes, returning identical assortment IDs,
    and resulting in exactly ONE assortment record in the database.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"ConcIdem {suffix}", "slug": f"conc-idem-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"CI-{suffix}"})).json()
        headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}

        idem_key = f"race-key-{suffix}"
        payload = {
            "code": f"ASSORT-CONC-{suffix}",
            "name": "Sortimento Concorrente",
            "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
            "product_ids": [],
        }

        # Fire two concurrent POST requests with the exact same idempotency key
        req1 = client.post("/api/v1/catalog/assortments", headers={**headers, "Idempotency-Key": idem_key}, json=payload)
        req2 = client.post("/api/v1/catalog/assortments", headers={**headers, "Idempotency-Key": idem_key}, json=payload)

        res1, res2 = await asyncio.gather(req1, req2)

        # Both must succeed (200 or 201)
        assert res1.status_code in {200, 201}, f"req1 failed: {res1.status_code} {res1.text}"
        assert res2.status_code in {200, 201}, f"req2 failed: {res2.status_code} {res2.text}"

        data1, data2 = res1.json(), res2.json()
        assert data1["id"] == data2["id"]

        # Exactly 1 assortment exists in DB
        with Session(engine) as db:
            set_platform_db_context(db)
            assorts = db.exec(
                select(Assortment).where(
                    Assortment.tenant_id == uuid.UUID(tenant["id"]),
                    Assortment.code == f"ASSORT-CONC-{suffix}",
                )
            ).all()
            assert len(assorts) == 1


@pytest.mark.asyncio
async def test_authenticated_author_derived_from_identity():
    """
    Local-auth compatibility smoke test plus direct identity invariant.
    The HTTP portion runs with the repository's explicit AUTH_MODE=disabled
    test boundary; it is not evidence of Supabase JWT verification.
    Mutations on assortments derive author from authenticated context.
    - If client sends a spoofed actor_id differing from authenticated user, server rejects with 403.
    - When actor_id is omitted, author is derived strictly from server identity.
    """
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"Author {suffix}", "slug": f"auth-{suffix}"})).json()
        store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"AU-{suffix}"})).json()

        # Create real user and active membership in tenant
        user_id = uuid.uuid4()
        with Session(engine) as db:
            set_platform_db_context(db)
            db.add(User(id=user_id, email=f"user-{suffix}@example.com", full_name="Authenticated User"))
            db.add(Membership(
                tenant_id=uuid.UUID(tenant["id"]),
                user_id=user_id,
                role=RoleEnum.MANAGER,
            ))
            db.commit()

        # Authenticated headers with user_id
        headers = {
            "X-Tenant-ID": tenant["id"],
            "X-Store-ID": store["id"],
            "X-User-ID": str(user_id),
        }

        # 1. Attempt to spoof a different actor_id -> 403 Forbidden
        spoofed_actor = str(uuid.uuid4())
        spoof_res = await client.post(
            "/api/v1/catalog/assortments",
            headers=headers,
            json={
                "code": f"ASSORT-SPOOF-{suffix}",
                "name": "Tentativa de Spoofing",
                "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
                "actor_id": spoofed_actor,
                "product_ids": [],
            },
        )
        assert spoof_res.status_code == 403
        assert "Ator não corresponde à identidade autenticada" in spoof_res.json()["detail"]

        # 2. Genuine request without spoofed actor_id -> succeeds and stamps user_id
        legit_res = await client.post(
            "/api/v1/catalog/assortments",
            headers=headers,
            json={
                "code": f"ASSORT-LEGIT-{suffix}",
                "name": "Sortimento Legítimo",
                "scopes": [{"store_id": store["id"], "sales_context": "COUNTER"}],
                "product_ids": [],
            },
        )
        assert legit_res.status_code == 201
        created = legit_res.json()

        # Verify in DB outbox event that actor_id is user_id
        with Session(engine) as db:
            set_platform_db_context(db)
            outbox = db.exec(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == uuid.UUID(tenant["id"]),
                    OutboxEvent.aggregate_id == created["id"],
                )
            ).first()
            assert outbox is not None
            assert outbox.event_type == "assortment.created"
            assert outbox.actor_id == user_id


def test_migration_069_preserves_counter_and_takeaway_without_presumed_table_or_delivery():
    """
    Verify the Migration 069 backfill contract non-vacuously in an isolated
    legacy tenant. The test reproduces the migration's DO-block semantics;
    Alembic's upgrade path is validated separately by the migration/check gate.
    1. Sets up a legacy tenant with a store and active sellable products, but no assortments.
    2. Replays the migration 069 backfill DO block for that tenant.
    3. Verifies that a LEGACY-DEFAULT assortment is materialized.
    4. Asserts that scopes created are strictly COUNTER and TAKEAWAY (len > 0),
       with zero scopes for TABLE, DELIVERY, or ECOMMERCE.
    """
    legacy_tenant_id = uuid.uuid4()
    legacy_store_id = uuid.uuid4()
    prod1_id = uuid.uuid4()
    prod2_id = uuid.uuid4()

    with Session(engine) as db:
        set_platform_db_context(db)
        db.add(Tenant(id=legacy_tenant_id, name="Legacy Tenant 069", slug=f"legacy-069-{uuid.uuid4().hex[:6]}"))
        db.add(Store(id=legacy_store_id, tenant_id=legacy_tenant_id, name="Loja Legado", code=f"LL-{uuid.uuid4().hex[:4]}", is_active=True))
        db.add(Product(id=prod1_id, tenant_id=legacy_tenant_id, name="Prod 1", sku=f"L1-{uuid.uuid4().hex[:4]}", is_active=True, available_for_sale=True))
        db.add(Product(id=prod2_id, tenant_id=legacy_tenant_id, name="Prod 2", sku=f"L2-{uuid.uuid4().hex[:4]}", is_active=True, available_for_sale=True))
        db.commit()

        # Run the migration 069 backfill DO block scoped to this tenant
        db.execute(text("""
        DO $$
        DECLARE
            r RECORD;
            v_assortment_id UUID;
            s RECORD;
        BEGIN
            FOR r IN SELECT DISTINCT p.tenant_id FROM products p WHERE p.tenant_id = :tid AND p.is_active = true AND p.available_for_sale = true LOOP
                IF EXISTS (SELECT 1 FROM stores WHERE tenant_id = r.tenant_id AND is_active = true) THEN
                    v_assortment_id := gen_random_uuid();
                    INSERT INTO assortments (id, tenant_id, code, name, description, status, version, created_at, updated_at)
                    VALUES (
                        v_assortment_id,
                        r.tenant_id,
                        'LEGACY-DEFAULT',
                        'Sortimento Legado — Balcão e Retirada',
                        'Materializado na migração 069 para preservar a publicação pré-existente de balcão e retirada sem classificação presumida.',
                        'ACTIVE',
                        1,
                        now(),
                        now()
                    )
                    ON CONFLICT (tenant_id, code) DO NOTHING;

                    SELECT id INTO v_assortment_id FROM assortments WHERE tenant_id = r.tenant_id AND code = 'LEGACY-DEFAULT';

                    FOR s IN SELECT id FROM stores WHERE tenant_id = r.tenant_id AND is_active = true LOOP
                        INSERT INTO assortment_scopes (id, tenant_id, assortment_id, store_id, channel_id, sales_context, created_at)
                        SELECT gen_random_uuid(), r.tenant_id, v_assortment_id, s.id, NULL, 'COUNTER', now()
                        WHERE NOT EXISTS (
                            SELECT 1 FROM assortment_scopes
                            WHERE tenant_id = r.tenant_id AND assortment_id = v_assortment_id
                              AND store_id = s.id AND sales_context = 'COUNTER' AND channel_id IS NULL
                        );

                        INSERT INTO assortment_scopes (id, tenant_id, assortment_id, store_id, channel_id, sales_context, created_at)
                        SELECT gen_random_uuid(), r.tenant_id, v_assortment_id, s.id, NULL, 'TAKEAWAY', now()
                        WHERE NOT EXISTS (
                            SELECT 1 FROM assortment_scopes
                            WHERE tenant_id = r.tenant_id AND assortment_id = v_assortment_id
                              AND store_id = s.id AND sales_context = 'TAKEAWAY' AND channel_id IS NULL
                        );
                    END LOOP;

                    INSERT INTO assortment_products (id, tenant_id, assortment_id, product_id, sort_order, created_at)
                    SELECT gen_random_uuid(), r.tenant_id, v_assortment_id, p.id, 100, now()
                    FROM products p
                    WHERE p.tenant_id = r.tenant_id
                      AND p.is_active = true
                      AND p.available_for_sale = true
                    ON CONFLICT (tenant_id, assortment_id, product_id) DO NOTHING;
                END IF;
            END LOOP;
        END $$;
        """), {"tid": legacy_tenant_id})
        db.commit()

        # Non-vacuous assertions
        legacy_assortment = db.exec(
            select(Assortment).where(Assortment.tenant_id == legacy_tenant_id, Assortment.code == "LEGACY-DEFAULT")
        ).first()
        assert legacy_assortment is not None, "Migration 069 must create LEGACY-DEFAULT assortment"

        legacy_scopes = db.exec(
            select(AssortmentScope.sales_context)
            .where(AssortmentScope.assortment_id == legacy_assortment.id)
        ).all()
        # Strictly non-vacuous assertion: at least 2 scopes must exist!
        assert len(legacy_scopes) == 2, f"Expected exactly 2 scopes, got {len(legacy_scopes)}"
        assert set(legacy_scopes) == {SalesContextEnum.COUNTER, SalesContextEnum.TAKEAWAY}

        # Assert products are linked
        prods = db.exec(
            select(AssortmentProduct)
            .where(AssortmentProduct.assortment_id == legacy_assortment.id)
        ).all()
        assert len(prods) == 2, f"Expected 2 products linked, got {len(prods)}"
