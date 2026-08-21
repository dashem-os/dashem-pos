import uuid
import asyncio
import pytest
import httpx

BASE_URL = "http://localhost:8002"

@pytest.mark.asyncio
async def test_pos3_gates_1_to_10():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # --- SETUP: Create Tenant, Store & Register ---
        t_slug = f"tenant-pay-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Payment", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Pay", "code": "LP"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}
        actor_id = str(uuid.uuid4())

        # --- GATE 1: Register & Cash Session Lifecycle ---
        reg_res = await client.post(
            "/api/v1/cash/registers",
            json={"store_id": s["id"], "name": "Caixa Principal", "code": "CX-01"},
            headers=headers
        )
        assert reg_res.status_code == 200
        reg = reg_res.json()

        session_res = await client.post(
            "/api/v1/cash/sessions/open",
            json={"store_id": s["id"], "register_id": reg["id"], "operator_id": actor_id, "opening_balance": 100.00},
            headers=headers
        )
        assert session_res.status_code == 200
        cash_session = session_res.json()
        assert cash_session["status"] == "OPEN"
        assert float(cash_session["opening_balance"]) == 100.00

        # --- SETUP: Catalog & Inventory ---
        # Product 1: Tracked inventory (Cabo 10mm, R$ 100.00)
        p1_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Cabo 10mm", "sku": f"CAB-10-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers
        )
        p1 = p1_res.json()
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": p1["id"], "store_id": s["id"], "cost_price": 50.00, "sale_price": 100.00},
            headers=headers
        )
        # Initial Stock Adjustment: +10.0
        await client.post(
            "/api/v1/inventory/adjust",
            json={"store_id": s["id"], "product_id": p1["id"], "actor_id": actor_id, "movement_type": "PURCHASE", "quantity": 10.0},
            headers=headers
        )

        # Service 2: Non-tracked inventory (Instalação, R$ 100.00)
        srv_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Instalação Elétrica", "sku": f"SERV-INS-{uuid.uuid4().hex[:4]}", "item_type": "SERVICE"},
            headers=headers
        )
        srv = srv_res.json()
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": srv["id"], "store_id": s["id"], "cost_price": 0.00, "sale_price": 100.00},
            headers=headers
        )

        # --- SETUP: Sale Creation & Checkout ---
        sale_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        sale = sale_res.json()

        # Add 2 items: 2x Cabo 10mm (R$ 200) + 1x Service (R$ 100) = R$ 300.00 Net Total
        await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p1["id"], "quantity": 2.0}, headers=headers)
        await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": srv["id"], "quantity": 1.0}, headers=headers)

        checkout_res = await client.post(f"/api/v1/sales/{sale['id']}/checkout", json={"actor_id": actor_id}, headers=headers)
        assert checkout_res.status_code == 200
        sale_checked = checkout_res.json()
        assert sale_checked["status"] == "AWAITING_PAYMENT"
        assert float(sale_checked["net_total"]) == 300.00

        # --- GATE 3: Overpayment Protection ---
        overpay_res = await client.post(
            "/api/v1/payments",
            json={"sale_id": sale["id"], "method": "PIX", "amount": 400.00},  # Exceeds R$ 300.00!
            headers=headers
        )
        assert overpay_res.status_code == 400
        assert "PAYMENT_EXCEEDS_OUTSTANDING_AMOUNT" in overpay_res.json()["detail"]

        # --- GATE 2, 4: Split Payment Multi-Method & Partial Payment Retention ---
        # Payment 1: PIX R$ 120.00
        pay1_res = await client.post(
            "/api/v1/payments",
            json={"sale_id": sale["id"], "method": "PIX", "amount": 120.00},
            headers=headers
        )
        assert pay1_res.status_code == 200
        pay1 = pay1_res.json()

        conf1 = await client.post(
            f"/api/v1/payments/{pay1['id']}/confirm",
            json={"actor_id": actor_id},
            headers={"X-Tenant-ID": t["id"], "X-Store-ID": s["id"], "Idempotency-Key": f"pay-key-1-{uuid.uuid4().hex[:6]}"}
        )
        assert conf1.status_code == 200
        assert conf1.json()["sale_status"] == "AWAITING_PAYMENT"  # Partial payment! Still awaiting!

        # GATE 8: Idempotent Retry of Payment 1 Confirmation -> Returns already_confirmed: True
        conf1_retry = await client.post(
            f"/api/v1/payments/{pay1['id']}/confirm",
            json={"actor_id": actor_id},
            headers={"X-Tenant-ID": t["id"], "X-Store-ID": s["id"], "Idempotency-Key": f"pay-key-1-{uuid.uuid4().hex[:6]}"}
        )
        assert conf1_retry.status_code == 200
        assert conf1_retry.json()["already_confirmed"] is True

        # Payment 2: CASH R$ 80.00 (Tendered R$ 100.00, Change R$ 20.00)
        pay2_res = await client.post(
            "/api/v1/payments",
            json={"sale_id": sale["id"], "method": "CASH", "amount": 80.00, "cash_session_id": cash_session["id"], "tendered_amount": 100.00},
            headers=headers
        )
        assert pay2_res.status_code == 200
        pay2 = pay2_res.json()
        assert float(pay2["change_amount"]) == 20.00

        conf2 = await client.post(
            f"/api/v1/payments/{pay2['id']}/confirm",
            json={"actor_id": actor_id},
            headers=headers
        )
        assert conf2.status_code == 200
        assert conf2.json()["sale_status"] == "AWAITING_PAYMENT"  # R$ 200 / R$ 300 paid!

        # Payment 3: CREDIT_CARD R$ 100.00 -> Completes R$ 300.00!
        pay3_res = await client.post(
            "/api/v1/payments",
            json={"sale_id": sale["id"], "method": "CREDIT_CARD", "amount": 100.00},
            headers=headers
        )
        assert pay3_res.status_code == 200
        pay3 = pay3_res.json()

        conf3 = await client.post(
            f"/api/v1/payments/{pay3['id']}/confirm",
            json={"actor_id": actor_id},
            headers=headers
        )
        assert conf3.status_code == 200
        assert conf3.json()["sale_status"] == "PAID"  # EXACT TRANSITION TO PAID!

        # --- GATE 5 & 6: Single Stock Decrement & Non-Tracked Bypass ---
        # Query final stock balance of Product 1 (Cabo 10mm) -> Initial 10.0 - 2.0 = 8.0
        bal_res = await client.get(f"/api/v1/inventory/balance?store_id={s['id']}&product_id={p1['id']}", headers=headers)
        assert bal_res.status_code == 200
        assert float(bal_res.json()["quantity"]) == 8.0

        # Query movements list for Product 1 -> Must contain exactly 1 SALE movement (-2.0)
        p1_movs_res = await client.get(f"/api/v1/inventory/movements?store_id={s['id']}&product_id={p1['id']}", headers=headers)
        p1_movs = p1_movs_res.json()
        sale_movs = [m for m in p1_movs if m["movement_type"] == "SALE"]
        assert len(sale_movs) == 1
        assert float(sale_movs[0]["quantity"]) == -2.0

        # Service 2 (Instalação) -> Must contain 0 InventoryMovement entries
        srv_movs_res = await client.get(f"/api/v1/inventory/movements?store_id={s['id']}&product_id={srv['id']}", headers=headers)
        srv_movs = srv_movs_res.json()
        assert len(srv_movs) == 0  # BYPASS OK!

        # --- GATE 1 & 6: Close Cash Session with Variance ---
        close_res = await client.post(
            f"/api/v1/cash/sessions/{cash_session['id']}/close",
            json={"operator_id": actor_id, "closing_balance": 180.00},
            headers=headers
        )
        assert close_res.status_code == 200
        closed_data = close_res.json()
        assert closed_data["status"] == "CLOSED"
        assert float(closed_data["expected_balance"]) == 180.00  # 100.00 opening + 80.00 cash sale
        assert float(closed_data["variance"]) == 0.00

@pytest.mark.asyncio
async def test_pos3_concurrent_sales_competing_for_last_stock_item():
    """
    CRITICAL TEST (STRICT STOCK POLICY):
    Stock = 1.0.
    Sale A (1 unit) and Sale B (1 unit) are both in AWAITING_PAYMENT.
    Confirming both payments SIMULTANEOUSLY via asyncio.gather:
    - Exactly ONE request succeeds (200 OK, Sale -> PAID, Stock -> 0.0).
    - The second request FAILS (400 Bad Request, INSUFFICIENT_STOCK).
    - Total final stock is 0.0 (never negative).
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-last-stock-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Last Stock", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Last Stock", "code": "LLS"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}
        actor_id = str(uuid.uuid4())

        # Product with EXACTLY 1.0 unit in stock
        p_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Última Unidade Rara", "sku": f"ULT-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers
        )
        p = p_res.json()
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": p["id"], "store_id": s["id"], "cost_price": 100.00, "sale_price": 250.00},
            headers=headers
        )
        # Initial Stock = 1.0
        await client.post(
            "/api/v1/inventory/adjust",
            json={"store_id": s["id"], "product_id": p["id"], "actor_id": actor_id, "movement_type": "PURCHASE", "quantity": 1.0},
            headers=headers
        )

        # Create Sale A (1 unit) & Checkout
        saleA_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        saleA = saleA_res.json()
        await client.post(f"/api/v1/sales/{saleA['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        await client.post(f"/api/v1/sales/{saleA['id']}/checkout", json={"actor_id": actor_id}, headers=headers)

        # Create Sale B (1 unit) & Checkout
        saleB_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        saleB = saleB_res.json()
        await client.post(f"/api/v1/sales/{saleB['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        await client.post(f"/api/v1/sales/{saleB['id']}/checkout", json={"actor_id": actor_id}, headers=headers)

        # Create Payment records for both Sales (PIX R$ 250.00 each)
        payA_res = await client.post("/api/v1/payments", json={"sale_id": saleA["id"], "method": "PIX", "amount": 250.00}, headers=headers)
        payA = payA_res.json()

        payB_res = await client.post("/api/v1/payments", json={"sale_id": saleB["id"], "method": "PIX", "amount": 250.00}, headers=headers)
        payB = payB_res.json()

        # SIMULTANEOUS PAYMENT CONFIRMATIONS FOR BOTH SALES!
        tasks = [
            client.post(f"/api/v1/payments/{payA['id']}/confirm", json={"actor_id": actor_id}, headers=headers),
            client.post(f"/api/v1/payments/{payB['id']}/confirm", json={"actor_id": actor_id}, headers=headers)
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        status_codes = [r.status_code for r in responses if hasattr(r, "status_code")]

        # EXACTLY ONE request must return 200 OK and ONE request must return 400 Bad Request
        assert status_codes.count(200) == 1, f"Expected exactly one 200 OK, got: {status_codes}"
        assert status_codes.count(400) == 1, f"Expected exactly one 400 Bad Request, got: {status_codes}"

        # Final stock balance MUST BE 0.0 (never negative)
        bal_res = await client.get(f"/api/v1/inventory/balance?store_id={s['id']}&product_id={p['id']}", headers=headers)
        assert float(bal_res.json()["quantity"]) == 0.0
