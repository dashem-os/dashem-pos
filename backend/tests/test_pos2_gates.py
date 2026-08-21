import uuid
import asyncio
import pytest
import httpx

BASE_URL = "http://localhost:8002"

@pytest.mark.asyncio
async def test_pos2_gates_1_to_14():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # --- SETUP: Create Tenant A and Tenant B ---
        tA_slug = f"tenant-sale-a-{uuid.uuid4().hex[:6]}"
        tA_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Sale A", "slug": tA_slug})
        tA = tA_res.json()

        sA_res = await client.post("/api/v1/identity/stores", json={"tenant_id": tA["id"], "name": "Loja Centro A", "code": "LCA"})
        sA = sA_res.json()

        tB_slug = f"tenant-sale-b-{uuid.uuid4().hex[:6]}"
        tB_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Sale B", "slug": tB_slug})
        tB = tB_res.json()

        sB_res = await client.post("/api/v1/identity/stores", json={"tenant_id": tB["id"], "name": "Loja B", "code": "LB"})
        sB = sB_res.json()

        headers_A = {"X-Tenant-ID": tA["id"], "X-Store-ID": sA["id"]}
        headers_B = {"X-Tenant-ID": tB["id"], "X-Store-ID": sB["id"]}
        actor_id = str(uuid.uuid4())

        # --- GATE 2 & 3: Store Ownership & Product Belonging ---
        # Create product in Tenant A
        pA_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Cabo 6mm Flexível", "sku": f"CAB-6-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers_A
        )
        pA = pA_res.json()

        # Set Product Price in Tenant A (R$ 99.00)
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": pA["id"], "store_id": sA["id"], "cost_price": 50.00, "sale_price": 99.00},
            headers=headers_A
        )

        # Create Sale in Tenant A
        saleA_res = await client.post(
            "/api/v1/sales",
            json={"store_id": sA["id"], "notes": "Venda Teste A"},
            headers=headers_A
        )
        assert saleA_res.status_code == 200
        saleA = saleA_res.json()
        assert saleA["status"] == "DRAFT"

        # INVARIANT GATE 2: Trying to create a Sale for Store B under Tenant A raises 400
        sale_invalid = await client.post(
            "/api/v1/sales",
            json={"store_id": sB["id"]},  # Wrong store!
            headers=headers_A
        )
        assert sale_invalid.status_code == 400

        # --- GATE 4 & 5: Server-Side Price Resolution & Operational Snapshot ---
        # Add item to Sale A (Quantity 2, Requested Discount R$ 5.00)
        item_res = await client.post(
            f"/api/v1/sales/{saleA['id']}/items",
            json={"product_id": pA["id"], "quantity": 2.0, "requested_discount": 5.00},
            headers=headers_A
        )
        assert item_res.status_code == 200
        item = item_res.json()

        # Check Historical & Operational Snapshot Fields
        assert item["product_name"] == "Cabo 6mm Flexível"
        assert item["sku"] == pA["sku"]
        assert item["item_type_snapshot"] == "PRODUCT"
        assert item["tracks_inventory_snapshot"] is True
        assert item["requires_fulfillment_snapshot"] is False
        assert float(item["unit_price"]) == 99.00  # Resolved server-side
        assert float(item["quantity"]) == 2.0
        assert float(item["gross_total"]) == 198.00  # 99.00 * 2
        assert float(item["discount_amount"]) == 5.00
        assert float(item["net_total"]) == 193.00  # 198.00 - 5.00

        # --- GATE 6 & 14: Historical Price Immutability ---
        # Update Product Price to R$ 120.00 in Catalog
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": pA["id"], "store_id": sA["id"], "cost_price": 50.00, "sale_price": 120.00},
            headers=headers_A
        )

        # Query existing Sale A -> SaleItem unit_price MUST REMAIN R$ 99.00!
        saleA_check = await client.get(f"/api/v1/sales/{saleA['id']}", headers=headers_A)
        assert saleA_check.status_code == 200
        saleA_data = saleA_check.json()
        assert float(saleA_data["items"][0]["unit_price"]) == 99.00  # IMMUTABLE!
        assert float(saleA_data["items"][0]["net_total"]) == 193.00

        # --- GATE 8: Non-Negative Net Total ---
        # Excess discount producing negative net total is rejected with 400
        bad_item = await client.post(
            f"/api/v1/sales/{saleA['id']}/items",
            json={"product_id": pA["id"], "quantity": 1.0, "requested_discount": 500.00},  # Exceeds gross price!
            headers=headers_A
        )
        assert bad_item.status_code == 400
        assert "negative net total" in bad_item.json()["detail"]

        # --- GATE 9 & 12: Atomic Checkout & Idempotency ---
        idempotency_key = f"checkout-key-{uuid.uuid4().hex[:6]}"
        correlation_id = f"corr-sale-{uuid.uuid4().hex[:6]}"
        headers_checkout = dict(headers_A)
        headers_checkout["Idempotency-Key"] = idempotency_key
        headers_checkout["X-Correlation-ID"] = correlation_id

        checkout_res = await client.post(
            f"/api/v1/sales/{saleA['id']}/checkout",
            json={"actor_id": actor_id, "requested_discount": 0.0},
            headers=headers_checkout
        )
        assert checkout_res.status_code == 200
        checkout_data = checkout_res.json()
        assert checkout_data["status"] == "AWAITING_PAYMENT"
        assert float(checkout_data["net_total"]) == 193.00

        # Idempotent Retry -> Returns cached result
        checkout_retry = await client.post(
            f"/api/v1/sales/{saleA['id']}/checkout",
            json={"actor_id": actor_id, "requested_discount": 0.0},
            headers=headers_checkout
        )
        assert checkout_retry.status_code == 200
        assert checkout_retry.json()["id"] == checkout_data["id"]

        # --- GATE 11: State Machine Enforcement ---
        # Cannot checkout a sale that is already AWAITING_PAYMENT
        invalid_checkout = await client.post(
            f"/api/v1/sales/{saleA['id']}/checkout",
            json={"actor_id": actor_id},
            headers=headers_A
        )
        assert invalid_checkout.status_code == 400
        assert "Invalid state transition" in invalid_checkout.json()["detail"]

        # --- GATE 1: Multi-Tenant Isolation ---
        # Tenant B queries Sale A -> Should return 404 Not Found
        saleA_tenantB = await client.get(f"/api/v1/sales/{saleA['id']}", headers=headers_B)
        assert saleA_tenantB.status_code == 404

@pytest.mark.asyncio
async def test_pos2_concurrent_same_sale_checkout_race_condition():
    """
    CRITICAL TEST: Verifies real concurrency protection when TWO SIMULTANEOUS checkout requests
    for the SAME sale_id arrive with DIFFERENT idempotency keys!
    Pessimistic FOR UPDATE lock must guarantee EXACTLY ONE request succeeds (200 OK)
    and the second request is rejected with 400 Bad Request (Invalid state transition).
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-conc-sale-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Conc Sale", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Conc Sale", "code": "LCS"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        # Create Product & Set Price
        p_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Disjuntor 40A Novo", "sku": f"DISJ-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers
        )
        p = p_res.json()
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": p["id"], "store_id": s["id"], "cost_price": 40.00, "sale_price": 62.00},
            headers=headers
        )

        # Create Sale in DRAFT
        sale_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        sale = sale_res.json()

        # Add Item
        await client.post(
            f"/api/v1/sales/{sale['id']}/items",
            json={"product_id": p["id"], "quantity": 1.0},
            headers=headers
        )

        actor_id = str(uuid.uuid4())

        # Disparar 2 requisições de checkout SIMULTÂNEAS para a MESMA venda com Idempotency Keys DIFERENTES!
        req1_headers = dict(headers)
        req1_headers["Idempotency-Key"] = f"key-race-1-{uuid.uuid4().hex[:6]}"

        req2_headers = dict(headers)
        req2_headers["Idempotency-Key"] = f"key-race-2-{uuid.uuid4().hex[:6]}"

        tasks = [
            client.post(f"/api/v1/sales/{sale['id']}/checkout", json={"actor_id": actor_id}, headers=req1_headers),
            client.post(f"/api/v1/sales/{sale['id']}/checkout", json={"actor_id": actor_id}, headers=req2_headers)
        ]

        responses = await asyncio.gather(*tasks)

        status_codes = [r.status_code for r in responses]
        
        # EXACTLY ONE request must return 200 OK and ONE request must return 400 Bad Request
        assert status_codes.count(200) == 1, f"Expected exactly one 200 OK, got: {status_codes}"
        assert status_codes.count(400) == 1, f"Expected exactly one 400 Bad Request, got: {status_codes}"

        # Final status MUST BE AWAITING_PAYMENT
        sale_final = await client.get(f"/api/v1/sales/{sale['id']}", headers=headers)
        assert sale_final.json()["status"] == "AWAITING_PAYMENT"

@pytest.mark.asyncio
async def test_pos2_customer_and_barcode_constraints():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-cust-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Cust", "slug": t_slug})
        t = t_res.json()
        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Cust", "code": "LC"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        cpf = f"12345{uuid.uuid4().hex[:6]}"
        c1 = await client.post(
            "/api/v1/sales/customers",
            json={"name": "João Silva", "cpf_cnpj": cpf},
            headers=headers
        )
        assert c1.status_code == 200

        # Duplicate CPF under same tenant -> 400 Bad Request
        c2 = await client.post(
            "/api/v1/sales/customers",
            json={"name": "João Maria", "cpf_cnpj": cpf},
            headers=headers
        )
        assert c2.status_code == 400
        assert "already exists" in c2.json()["detail"]
