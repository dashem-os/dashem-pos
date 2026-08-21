import uuid
import pytest
import httpx

BASE_URL = "http://localhost:8002"

@pytest.mark.asyncio
async def test_pos4_gates_1_to_14():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # --- SETUP: Create Tenant, Store & Product ---
        t_slug = f"tenant-fisc-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Fiscal", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Fiscal", "code": "LF"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}
        actor_id = str(uuid.uuid4())

        p_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Disjuntor 40A", "sku": f"DISJ-{uuid.uuid4().hex[:4]}", "item_type": "PRODUCT"},
            headers=headers
        )
        p = p_res.json()
        await client.post(
            "/api/v1/catalog/prices",
            json={"product_id": p["id"], "store_id": s["id"], "cost_price": 30.00, "sale_price": 62.00},
            headers=headers
        )
        await client.post(
            "/api/v1/inventory/adjust",
            json={"store_id": s["id"], "product_id": p["id"], "actor_id": actor_id, "movement_type": "PURCHASE", "quantity": 10.0},
            headers=headers
        )

        # --- SETUP: Create Sale A & Checkout ---
        saleA_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        saleA = saleA_res.json()
        await client.post(f"/api/v1/sales/{saleA['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        await client.post(f"/api/v1/sales/{saleA['id']}/checkout", json={"actor_id": actor_id}, headers=headers)

        # --- GATE 2: Non-PAID Sale Cannot Issue Fiscal Document ---
        gate2_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": saleA["id"], "actor_id": actor_id, "document_type": "NFCE"},
            headers=headers
        )
        assert gate2_res.status_code == 400
        assert "ONLY_PAID_SALES_CAN_ISSUE_FISCAL" in gate2_res.json()["detail"]

        # --- Pay Sale A -> Transition to PAID ---
        payA_res = await client.post("/api/v1/payments", json={"sale_id": saleA["id"], "method": "PIX", "amount": 62.00}, headers=headers)
        payA = payA_res.json()
        await client.post(f"/api/v1/payments/{payA['id']}/confirm", json={"actor_id": actor_id}, headers=headers)

        # --- GATE 8 & 9: Simulate REJECTED Issuance (Non-Destructive Rejection) ---
        gate8_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": saleA["id"], "actor_id": actor_id, "document_type": "NFCE", "simulate_status": "REJECTED"},
            headers=headers
        )
        assert gate8_res.status_code == 200
        gate8_data = gate8_res.json()
        assert gate8_data["fiscal_document"]["status"] == "REJECTED"
        assert gate8_data["fiscal_document"]["rejection_code"] == "539"
        assert gate8_data["fiscal_document"]["request_hash"] is not None
        # Sale status REMAINS PAID!
        assert gate8_data["sale_status"] == "PAID"

        # Stock REMAINS 9.0 (not reverted)
        bal_res = await client.get(f"/api/v1/inventory/balance?store_id={s['id']}&product_id={p['id']}", headers=headers)
        assert float(bal_res.json()["quantity"]) == 9.0

        # --- GATE 3, 4, 7, 10: Successful Issuance, AUTHORIZED & COMPLETED Transition ---
        gate3_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": saleA["id"], "actor_id": actor_id, "document_type": "NFCE"},
            headers={**headers, "X-Correlation-ID": "corr-fisc-auth-100"}
        )
        assert gate3_res.status_code == 200
        gate3_data = gate3_res.json()
        docA = gate3_data["fiscal_document"]
        assert docA["status"] == "AUTHORIZED"
        assert len(docA["access_key"]) == 44
        # SALE TRANSITIONS TO COMPLETED!
        assert gate3_data["sale_status"] == "COMPLETED"

        # --- GATE 5 & 11: Idempotent Retry of Authorized Document ---
        retry_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": saleA["id"], "actor_id": actor_id, "document_type": "NFCE"},
            headers=headers
        )
        assert retry_res.status_code == 200
        assert retry_res.json()["already_processed"] is True

        # --- GATE 13: Formal Fiscal Cancellation ---
        canc_res = await client.post(
            f"/api/v1/fiscal/documents/{docA['id']}/cancel",
            json={"actor_id": actor_id, "reason": "Desistência do cliente antes da entrega"},
            headers=headers
        )
        assert canc_res.status_code == 200
        canc_data = canc_res.json()
        assert canc_data["status"] == "CANCELED"
        assert canc_data["canceled_at"] is not None

        # --- GATE 11 (NOT_REQUIRED Flow): document_type = NONE -> Fiscal NOT_REQUIRED & Sale COMPLETED ---
        saleB_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        saleB = saleB_res.json()
        await client.post(f"/api/v1/sales/{saleB['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        await client.post(f"/api/v1/sales/{saleB['id']}/checkout", json={"actor_id": actor_id}, headers=headers)

        payB_res = await client.post("/api/v1/payments", json={"sale_id": saleB["id"], "method": "PIX", "amount": 62.00}, headers=headers)
        payB = payB_res.json()
        await client.post(f"/api/v1/payments/{payB['id']}/confirm", json={"actor_id": actor_id}, headers=headers)

        nr_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": saleB["id"], "actor_id": actor_id, "document_type": "NONE"},
            headers=headers
        )
        assert nr_res.status_code == 200
        nr_data = nr_res.json()
        assert nr_data["fiscal_document"]["status"] == "NOT_REQUIRED"
        assert nr_data["sale_status"] == "COMPLETED"

        # --- GATE 14 (Contingency Policy): Contingency leaves Sale in PAID (does NOT auto-complete) ---
        saleC_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        saleC = saleC_res.json()
        await client.post(f"/api/v1/sales/{saleC['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        await client.post(f"/api/v1/sales/{saleC['id']}/checkout", json={"actor_id": actor_id}, headers=headers)

        payC_res = await client.post("/api/v1/payments", json={"sale_id": saleC["id"], "method": "PIX", "amount": 62.00}, headers=headers)
        payC = payC_res.json()
        await client.post(f"/api/v1/payments/{payC['id']}/confirm", json={"actor_id": actor_id}, headers=headers)

        cont_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": saleC["id"], "actor_id": actor_id, "document_type": "NFCE", "simulate_status": "CONTINGENCY"},
            headers=headers
        )
        assert cont_res.status_code == 200
        cont_data = cont_res.json()
        assert cont_data["fiscal_document"]["status"] == "CONTINGENCY"
        # Sale status REMAINS PAID (does NOT auto-complete on contingency!)
        assert cont_data["sale_status"] == "PAID"
