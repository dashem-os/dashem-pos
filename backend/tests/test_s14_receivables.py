import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.payment import Payment
from app.models.receivable import Receivable, ReceivableAllocation, ReceivableLedgerEntry
from app.models.sale import Sale


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _context(client: httpx.AsyncClient, prefix: str):
    suffix = uuid.uuid4().hex[:8]
    actor = str(uuid.uuid4())
    tenant = (await client.post("/api/v1/identity/tenants", json={"name": f"{prefix} {suffix}", "slug": f"{prefix.lower()}-{suffix}"})).json()
    store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"{prefix[:3].upper()}-{suffix}"})).json()
    headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
    customer = (await client.post("/api/v1/sales/customers", headers=headers, json={
        "name": f"Cliente {prefix}", "cpf_cnpj": f"{uuid.uuid4().int % 10**11:011d}",
    })).json()
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": "Produto a prazo", "sku": f"CR-{suffix}", "unit": "UN", "tracks_inventory": False,
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store["id"], "cost_price": 10, "sale_price": 60,
    })
    return tenant, store, headers, actor, customer, product


async def _negotiation(client, store, headers, actor, customer, product, suffix, quantity=1):
    order = (await client.post("/api/v1/orders", headers={**headers, "Idempotency-Key": f"order-{suffix}"}, json={
        "store_id": store["id"], "customer_id": customer["id"], "actor_id": actor,
    })).json()
    launched = await client.post(f"/api/v1/orders/{order['id']}/items", headers={
        **headers, "Idempotency-Key": f"item-{suffix}",
    }, json={"product_id": product["id"], "quantity": quantity, "actor_id": actor})
    assert launched.status_code == 200, launched.text
    opened = await client.post("/api/v1/negotiations", headers={
        **headers, "Idempotency-Key": f"negotiation-{suffix}",
    }, json={"store_id": store["id"], "order_ids": [order["id"]], "actor_id": actor})
    assert opened.status_code == 200, opened.text
    return opened.json()


@pytest.mark.asyncio
async def test_s14_credit_issues_sale_and_receivable_atomically_without_cash_receipt():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store, headers, actor, customer, product = await _context(client, "Credit")
        policy = await client.put(f"/api/v1/receivables/customers/{customer['id']}/policy", headers=headers, json={
            "credit_limit": 100, "terms_days": 30, "allow_overdue": False, "status": "ACTIVE", "actor_id": actor,
        })
        assert policy.status_code == 200, policy.text
        negotiation = await _negotiation(client, store, headers, actor, customer, product, uuid.uuid4().hex)
        key = f"credit-{uuid.uuid4()}"
        command = {
            "customer_id": customer["id"], "expected_version": negotiation["version"],
            "due_at": (datetime.utcnow() + timedelta(days=20)).isoformat(),
            "reason": "Venda autorizada conforme política", "actor_id": actor,
        }
        issued = await client.post(f"/api/v1/receivables/negotiations/{negotiation['id']}/issue", headers={
            **headers, "Idempotency-Key": key,
        }, json=command)
        assert issued.status_code == 200, issued.text
        title = issued.json()
        assert float(title["principal_amount"]) == 60
        assert float(title["balance"]) == 60
        assert title["sale_id"]
        retry = await client.post(f"/api/v1/receivables/negotiations/{negotiation['id']}/issue", headers={
            **headers, "Idempotency-Key": key,
        }, json=command)
        assert retry.status_code == 200
        assert retry.json()["id"] == title["id"]
        projection = (await client.get(f"/api/v1/receivables/customers/{customer['id']}/policy", headers=headers)).json()
        assert float(projection["exposure"]) == 60
        assert float(projection["available"]) == 40

        second = await _negotiation(client, store, headers, actor, customer, product, uuid.uuid4().hex)
        rejected = await client.post(f"/api/v1/receivables/negotiations/{second['id']}/issue", headers={
            **headers, "Idempotency-Key": f"credit-{uuid.uuid4()}",
        }, json={"customer_id": customer["id"], "expected_version": second["version"], "reason": "Excede limite", "actor_id": actor})
        assert rejected.status_code == 409

        _foreign_tenant, _foreign_store, foreign_headers, *_ = await _context(client, "ForeignCredit")
        assert (await client.get("/api/v1/receivables", headers=foreign_headers)).json() == []

    with Session(engine) as db:
        set_platform_db_context(db)
        persisted = db.get(Receivable, uuid.UUID(title["id"]))
        assert persisted is not None and persisted.sale_id is not None
        assert len(db.exec(select(ReceivableAllocation).where(ReceivableAllocation.receivable_id == persisted.id)).all()) == 1
        assert len(db.exec(select(ReceivableLedgerEntry).where(ReceivableLedgerEntry.receivable_id == persisted.id)).all()) == 1
        sale = db.get(Sale, persisted.sale_id)
        assert sale is not None and sale.customer_id == uuid.UUID(customer["id"])
        assert db.exec(select(Payment).where(Payment.sale_id == sale.id)).all() == []
