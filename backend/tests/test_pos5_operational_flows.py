import uuid
import pytest
import httpx
from decimal import Decimal

BASE_URL = "http://localhost:8002"

@pytest.mark.asyncio
async def test_pos5_item_quantity_update_delete_and_totals():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Setup Tenant, Store, Products
        t_slug = f"tenant-op-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Op", "slug": t_slug})
        assert t_res.status_code == 200
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Op", "code": "LOP"})
        assert s_res.status_code == 200
        s = s_res.json()

        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        # Create Product 1 (R$ 50.00) and Product 2 (R$ 30.00)
        p1_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Produto Alpha", "sku": f"ALP-{uuid.uuid4().hex[:4]}", "barcode": "789100000001"},
            headers=headers
        )
        p1 = p1_res.json()
        await client.post("/api/v1/catalog/prices", json={"product_id": p1["id"], "store_id": s["id"], "cost_price": 20.0, "sale_price": 50.0}, headers=headers)

        p2_res = await client.post(
            "/api/v1/catalog/products",
            json={"name": "Produto Beta", "sku": f"BET-{uuid.uuid4().hex[:4]}", "barcode": "789100000002"},
            headers=headers
        )
        p2 = p2_res.json()
        await client.post("/api/v1/catalog/prices", json={"product_id": p2["id"], "store_id": s["id"], "cost_price": 10.0, "sale_price": 30.0}, headers=headers)

        # Create Sale
        sale_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        sale = sale_res.json()

        # Add Item 1 (qty 2 -> 100.00)
        i1_res = await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p1["id"], "quantity": 2.0}, headers=headers)
        assert i1_res.status_code == 200
        i1 = i1_res.json()

        # Add Item 2 (qty 1 -> 30.00)
        i2_res = await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p2["id"], "quantity": 1.0}, headers=headers)
        assert i2_res.status_code == 200
        i2 = i2_res.json()

        # Check sale totals (Gross: 130.00, Net: 130.00)
        s_check = await client.get(f"/api/v1/sales/{sale['id']}", headers=headers)
        s_data = s_check.json()
        assert float(s_data["gross_total"]) == 130.00
        assert float(s_data["net_total"]) == 130.00
        assert len(s_data["items"]) == 2

        # Update Item 1 quantity to 4 (Gross: 4*50 + 30 = 230.00)
        patch_res = await client.patch(
            f"/api/v1/sales/{sale['id']}/items/{i1['id']}",
            json={"quantity": 4.0},
            headers=headers
        )
        assert patch_res.status_code == 200

        s_check = await client.get(f"/api/v1/sales/{sale['id']}", headers=headers)
        s_data = s_check.json()
        assert float(s_data["gross_total"]) == 230.00
        assert float(s_data["net_total"]) == 230.00

        # Delete Item 2 (Gross becomes 200.00)
        del_res = await client.delete(f"/api/v1/sales/{sale['id']}/items/{i2['id']}", headers=headers)
        assert del_res.status_code == 200
        s_data = del_res.json()
        assert float(s_data["gross_total"]) == 200.00
        assert float(s_data["net_total"]) == 200.00
        assert len(s_data["items"]) == 1

@pytest.mark.asyncio
async def test_pos5_sale_discount_and_validation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-disc-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Disc", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Disc", "code": "LD"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        p_res = await client.post("/api/v1/catalog/products", json={"name": "Item Luxo", "sku": f"LX-{uuid.uuid4().hex[:4]}"}, headers=headers)
        p = p_res.json()
        await client.post("/api/v1/catalog/prices", json={"product_id": p["id"], "store_id": s["id"], "cost_price": 50.0, "sale_price": 100.0}, headers=headers)

        sale_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        sale = sale_res.json()

        await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p["id"], "quantity": 2.0}, headers=headers) # Gross: 200.00

        # Rejects negative discount
        neg_res = await client.post(f"/api/v1/sales/{sale['id']}/discount", json={"discount_type": "FIXED", "value": -10.0}, headers=headers)
        assert neg_res.status_code == 400

        # Rejects discount > gross
        over_res = await client.post(f"/api/v1/sales/{sale['id']}/discount", json={"discount_type": "FIXED", "value": 250.0}, headers=headers)
        assert over_res.status_code == 400

        # Rejects percentage > 100
        over_pct = await client.post(f"/api/v1/sales/{sale['id']}/discount", json={"discount_type": "PERCENTAGE", "value": 110.0}, headers=headers)
        assert over_pct.status_code == 400

        # Valid Fixed discount: R$ 30.00 -> Net: 170.00
        disc_res = await client.post(f"/api/v1/sales/{sale['id']}/discount", json={"discount_type": "FIXED", "value": 30.0}, headers=headers)
        assert disc_res.status_code == 200
        disc_data = disc_res.json()
        assert float(disc_data["gross_total"]) == 200.00
        assert float(disc_data["discount_total"]) == 30.00
        assert float(disc_data["net_total"]) == 170.00

        # Valid Percentage discount: 10% on 200 = 20.00 -> Net: 180.00
        pct_res = await client.post(f"/api/v1/sales/{sale['id']}/discount", json={"discount_type": "PERCENTAGE", "value": 10.0}, headers=headers)
        assert pct_res.status_code == 200
        pct_data = pct_res.json()
        assert float(pct_data["discount_total"]) == 20.00
        assert float(pct_data["net_total"]) == 180.00

@pytest.mark.asyncio
async def test_pos5_cancel_sale():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-canc-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Canc", "slug": t_slug})
        t = t_res.json()

        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Canc", "code": "LC"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        p_res = await client.post("/api/v1/catalog/products", json={"name": "Item A", "sku": f"IA-{uuid.uuid4().hex[:4]}"}, headers=headers)
        p = p_res.json()
        await client.post("/api/v1/catalog/prices", json={"product_id": p["id"], "store_id": s["id"], "cost_price": 10.0, "sale_price": 50.0}, headers=headers)

        sale_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        sale = sale_res.json()
        await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)

        # Cancel Sale
        canc_res = await client.post(f"/api/v1/sales/{sale['id']}/cancel", json={"reason": "Cliente desistiu"}, headers=headers)
        assert canc_res.status_code == 200
        canc_data = canc_res.json()
        assert canc_data["status"] == "CANCELED"

        # Cannot add item to canceled sale
        err_res = await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        assert err_res.status_code == 400

@pytest.mark.asyncio
async def test_pos5_catalog_search():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-src-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Search", "slug": t_slug})
        t = t_res.json()
        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Search", "code": "LS"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}

        await client.post(
            "/api/v1/catalog/products",
            json={"name": "Furadeira de Impacto 500W", "sku": "FUR-500", "barcode": "789000111222"},
            headers=headers
        )

        # Search by barcode
        res_bc = await client.get("/api/v1/catalog/products?search=789000111222", headers=headers)
        assert res_bc.status_code == 200
        assert len(res_bc.json()) == 1
        assert res_bc.json()[0]["sku"] == "FUR-500"

        # Search by SKU
        res_sku = await client.get("/api/v1/catalog/products?search=FUR-500", headers=headers)
        assert res_sku.status_code == 200
        assert len(res_sku.json()) == 1

        # Search by name substring
        res_name = await client.get("/api/v1/catalog/products?search=Furadeira", headers=headers)
        assert res_name.status_code == 200
        assert len(res_name.json()) == 1

@pytest.mark.asyncio
async def test_pos5_split_payment_stock_and_state_matrix():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        t_slug = f"tenant-split-{uuid.uuid4().hex[:6]}"
        t_res = await client.post("/api/v1/identity/tenants", json={"name": "Tenant Split", "slug": t_slug})
        t = t_res.json()
        s_res = await client.post("/api/v1/identity/stores", json={"tenant_id": t["id"], "name": "Loja Split", "code": "LSP"})
        s = s_res.json()
        headers = {"X-Tenant-ID": t["id"], "X-Store-ID": s["id"]}
        actor_id = str(uuid.uuid4())

        # Create Register and Open Cash Session
        reg_res = await client.post("/api/v1/cash/registers", json={"store_id": s["id"], "name": "Caixa 01", "code": "CX01"}, headers=headers)
        reg = reg_res.json()
        cs_res = await client.post("/api/v1/cash/sessions/open", json={"store_id": s["id"], "register_id": reg["id"], "operator_id": actor_id, "opening_balance": 100.0}, headers=headers)
        cs = cs_res.json()

        # Product with stock initial = 10
        p_res = await client.post("/api/v1/catalog/products", json={"name": "Parafuso Inox", "sku": f"PAR-{uuid.uuid4().hex[:4]}", "tracks_inventory": True}, headers=headers)
        p = p_res.json()
        await client.post("/api/v1/catalog/prices", json={"product_id": p["id"], "store_id": s["id"], "cost_price": 5.0, "sale_price": 20.0}, headers=headers)
        await client.post("/api/v1/inventory/adjust", json={"store_id": s["id"], "product_id": p["id"], "actor_id": actor_id, "movement_type": "PURCHASE", "quantity": 10.0}, headers=headers)

        # Create Sale with 3 units (Total: R$ 60.00)
        sale_res = await client.post("/api/v1/sales", json={"store_id": s["id"]}, headers=headers)
        sale = sale_res.json()
        await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p["id"], "quantity": 3.0}, headers=headers)

        # Checkout -> AWAITING_PAYMENT
        chk_res = await client.post(f"/api/v1/sales/{sale['id']}/checkout", json={"actor_id": actor_id}, headers=headers)
        assert chk_res.status_code == 200
        chk_sale = chk_res.json()
        assert chk_sale["status"] == "AWAITING_PAYMENT"
        assert float(chk_sale["net_total"]) == 60.00

        # State machine verification: Re-checkout on AWAITING_PAYMENT is rejected with 400
        chk_again = await client.post(f"/api/v1/sales/{sale['id']}/checkout", json={"actor_id": actor_id}, headers=headers)
        assert chk_again.status_code == 400


        # Payment 1: Split - R$ 20.00 in CASH
        pay1_res = await client.post(
            "/api/v1/payments",
            json={"sale_id": sale["id"], "method": "CASH", "amount": 20.0, "cash_session_id": cs["id"], "tendered_amount": 50.0},
            headers=headers
        )
        assert pay1_res.status_code == 200
        pay1 = pay1_res.json()
        assert float(pay1["tendered_amount"]) == 50.0
        assert float(pay1["change_amount"]) == 30.0

        # Confirm Payment 1
        conf1 = await client.post(f"/api/v1/payments/{pay1['id']}/confirm", json={"actor_id": actor_id}, headers=headers)
        assert conf1.status_code == 200
        assert conf1.json()["sale_status"] == "AWAITING_PAYMENT"  # Not yet fully paid (20/60)

        # INVARIANT CHECK: Cannot modify items, discount or cancel sale after 1st confirmed payment!
        err_add = await client.post(f"/api/v1/sales/{sale['id']}/items", json={"product_id": p["id"], "quantity": 1.0}, headers=headers)
        assert err_add.status_code == 400

        err_disc = await client.post(f"/api/v1/sales/{sale['id']}/discount", json={"discount_type": "FIXED", "value": 5.0}, headers=headers)
        assert err_disc.status_code == 400

        err_canc = await client.post(f"/api/v1/sales/{sale['id']}/cancel", headers=headers)
        assert err_canc.status_code == 400

        # Query payments for sale
        pays_res = await client.get(f"/api/v1/payments?sale_id={sale['id']}", headers=headers)
        assert pays_res.status_code == 200
        assert len(pays_res.json()) == 1

        # Payment 2: Remaining R$ 40.00 via PIX
        pay2_res = await client.post(
            "/api/v1/payments",
            json={"sale_id": sale["id"], "method": "PIX", "amount": 40.0},
            headers=headers
        )
        assert pay2_res.status_code == 200
        pay2 = pay2_res.json()

        conf2 = await client.post(f"/api/v1/payments/{pay2['id']}/confirm", json={"actor_id": actor_id}, headers=headers)
        assert conf2.status_code == 200
        assert conf2.json()["sale_status"] == "PAID"  # Total 60.00 reached!

        # Stock balance check: was 10, subtracted 3 -> MUST BE EXACTLY 7!
        bal_res = await client.get(f"/api/v1/inventory/balance?store_id={s['id']}&product_id={p['id']}", headers=headers)
        assert bal_res.status_code == 200
        assert float(bal_res.json()["quantity"]) == 7.0

        # Fiscal document issue
        fisc_res = await client.post(
            "/api/v1/fiscal/documents/issue",
            json={"sale_id": sale["id"], "actor_id": actor_id, "document_type": "NFCE"},
            headers=headers
        )
        assert fisc_res.status_code == 200
        assert fisc_res.json()["sale_status"] == "COMPLETED"
        assert fisc_res.json()["fiscal_document"]["status"] == "AUTHORIZED"
