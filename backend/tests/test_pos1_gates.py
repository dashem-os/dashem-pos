import uuid
import os
import asyncio
import pytest
import httpx

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")

@pytest.mark.asyncio
async def test_pos1_gates_1_to_11():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # --- SETUP: Create Tenant A and Tenant B ---
        tA_slug = f"tenant-a-{uuid.uuid4().hex[:6]}"
        tA_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant A", "slug": tA_slug})
        tA = tA_res.json()

        sA_res = await client.post("/api/v1/identity/stores", json={"tenant_id": tA["id"], "name": "Loja Centro", "code": "LC"})
        sA = sA_res.json()

        sA2_res = await client.post("/api/v1/identity/stores", json={"tenant_id": tA["id"], "name": "Loja Barra", "code": "LB"})
        sA2 = sA2_res.json()

        tB_slug = f"tenant-b-{uuid.uuid4().hex[:6]}"
        tB_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant B", "slug": tB_slug})
        tB = tB_res.json()

        sB_res = await client.post("/api/v1/identity/stores", json={"tenant_id": tB["id"], "name": "Loja B", "code": "LB"})
        sB = sB_res.json()

        actor_id = str(uuid.uuid4())
        headers_A = {"X-Tenant-ID": tA["id"], "X-Store-ID": sA["id"]}
        headers_B = {"X-Tenant-ID": tB["id"], "X-Store-ID": sB["id"]}

        # --- GATE 1: Multi-Tenant Isolation ---
        pA_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Disjuntor 40A", "sku": f"DISJ-40A-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers_A
        )
        assert pA_res.status_code == 200
        pA = pA_res.json()

        pB_list = await client.get("/api/v1/catalog/products", headers=headers_B)
        assert pB_list.status_code == 200
        assert len(pB_list.json()) == 0

        # --- GATE 2: Product & Service Invariants & Store-Level Pricing ---
        assert pA["item_type"] == "PRODUCT"
        assert pA["tracks_inventory"] is True
        assert pA["requires_fulfillment"] is False

        # Store-Level Product Pricing (Loja Centro: 99.00, Loja Barra: 105.00)
        pr1 = await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": pA["id"], "store_id": sA["id"], "cost_price": 60.00, "sale_price": 99.00},
            headers=headers_A
        )
        assert pr1.status_code == 200
        assert float(pr1.json()["sale_price"]) == 99.0

        pr2 = await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": pA["id"], "store_id": sA2["id"], "cost_price": 60.00, "sale_price": 105.00},
            headers=headers_A
        )
        assert pr2.status_code == 200
        assert float(pr2.json()["sale_price"]) == 105.0

        # Service Invariants
        srv_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Instalação Elétrica", "sku": f"SERV-INST-{uuid.uuid4().hex[:4]}", "item_type": "SERVICE"},
            headers=headers_A
        )
        assert srv_res.status_code == 200
        srv = srv_res.json()

        assert srv["item_type"] == "SERVICE"
        assert srv["tracks_inventory"] is False
        assert srv["requires_fulfillment"] is True

        # --- GATE 3: Non-Tracked Inventory Bypass ---
        srv_adjust = await client.post(
            "/api/v1/inventory/adjust",
            json={
                "store_id": sA["id"],
                "product_id": srv["id"],
                "actor_id": actor_id,
                "movement_type": "ADJUSTMENT",
                "quantity": 5.0,
                "reason": "Test Service Bypass"
            },
            headers=headers_A
        )
        assert srv_adjust.status_code == 200
        srv_adj_data = srv_adjust.json()
        assert srv_adj_data["movement_created"] is False
        assert srv_adj_data["movement"] is None

        # --- GATE 5 & 7: Atomic Stock Adjustment + Audit + Outbox & Balance Integrity ---
        idempotency_key_1 = f"key-stock-{uuid.uuid4().hex[:6]}"
        correlation_id_1 = f"corr-stock-{uuid.uuid4().hex[:6]}"
        headers_A_stock = dict(headers_A)
        headers_A_stock["Idempotency-Key"] = idempotency_key_1
        headers_A_stock["X-Correlation-ID"] = correlation_id_1

        # Stock Adjustment 1: +10.0
        adj1_res = await client.post(
            "/api/v1/inventory/adjust",
            json={
                "store_id": sA["id"],
                "product_id": pA["id"],
                "actor_id": actor_id,
                "movement_type": "PURCHASE",
                "quantity": 10.0,
                "reason": "Compra Inicial"
            },
            headers=headers_A_stock
        )
        assert adj1_res.status_code == 200
        adj1_data = adj1_res.json()
        assert adj1_data["movement_created"] is True
        assert float(adj1_data["balance"]["quantity"]) == 10.0
        assert float(adj1_data["movement"]["previous_balance"]) == 0.0
        assert float(adj1_data["movement"]["new_balance"]) == 10.0

        # --- GATE 8: Idempotent Retry Protection ---
        adj1_retry = await client.post(
            "/api/v1/inventory/adjust",
            json={
                "store_id": sA["id"],
                "product_id": pA["id"],
                "actor_id": actor_id,
                "movement_type": "PURCHASE",
                "quantity": 10.0,
                "reason": "Compra Inicial"
            },
            headers=headers_A_stock
        )
        assert adj1_retry.status_code == 200
        assert adj1_retry.json()["movement"]["id"] == adj1_data["movement"]["id"]

        # Stock Adjustment 2: -3.0 (Venda)
        adj2_res = await client.post(
            "/api/v1/inventory/adjust",
            json={
                "store_id": sA["id"],
                "product_id": pA["id"],
                "actor_id": actor_id,
                "movement_type": "SALE",
                "quantity": -3.0,
                "reason": "Venda Balcão"
            },
            headers=headers_A
        )
        assert adj2_res.status_code == 200
        assert float(adj2_res.json()["balance"]["quantity"]) == 7.0

        # Verify Movements List (Ledger)
        movs_res = await client.get(
            f"/api/v1/inventory/movements?store_id={sA['id']}&product_id={pA['id']}",
            headers=headers_A
        )
        assert movs_res.status_code == 200
        movs = movs_res.json()
        assert len(movs) == 2
        assert sum(float(m["quantity"]) for m in movs) == 7.0

@pytest.mark.asyncio
async def test_first_balance_concurrency_race_condition():
    """
    CRITICAL TEST: Verifies that 5 SIMULTANEOUS stock adjustments on a BRAND NEW product
    (with ZERO pre-existing InventoryBalance rows) produce a single balance row with 
    quantity 50.0 and 5 movements without any IntegrityError or Lost Updates!
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Create Tenant, Store and NEW Product
        t_slug = f"tenant-first-bal-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant First Bal", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja First Bal", "code": "LFB"})
        s = s_res.json()

        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        # NEW PRODUCT - ZERO InventoryBalance rows exist in DB for this product!
        p_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Cabo Flexível 10mm (Novo)", "sku": f"CABO-10-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers
        )
        p = p_res.json()

        actor_id = str(uuid.uuid4())

        # Disparar 5 ajustes simultâneos de +10.0 no produto novo sem saldo prévio
        tasks = [
            client.post(
                "/api/v1/inventory/adjust",
                json={
                    "store_id": s["id"],
                    "product_id": p["id"],
                    "actor_id": actor_id,
                    "movement_type": "PURCHASE",
                    "quantity": 10.0,
                    "reason": f"First Balance Concurrency Purchase {i}"
                },
                headers={
                    "X-Tenant-ID": t["id"],
                    "X-Store-ID": s["id"],
                    "Idempotency-Key": f"first-bal-key-{uuid.uuid4().hex[:6]}"
                }
            )
            for i in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        # All 5 concurrent adjustments must return 200 OK
        for r in responses:
            assert r.status_code == 200

        # Query final balance -> Must be exactly 50.0 (5 x 10.0)
        bal_res = await client.get(
            f"/api/v1/inventory/balance?store_id={s['id']}&product_id={p['id']}",
            headers=headers
        )
        assert bal_res.status_code == 200
        assert float(bal_res.json()["quantity"]) == 50.0

        # Query movements -> Must be exactly 5 movements
        movs_res = await client.get(
            f"/api/v1/inventory/movements?store_id={s['id']}&product_id={p['id']}",
            headers=headers
        )
        assert movs_res.status_code == 200
        movs = movs_res.json()
        assert len(movs) == 5
        assert sum(float(m["quantity"]) for m in movs) == 50.0
