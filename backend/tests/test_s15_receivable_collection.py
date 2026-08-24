import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.receivable import (
    Receivable, ReceivableAgreement, ReceivableAgreementItem,
    ReceivableReceipt, ReceivableReceiptAllocation,
)
from test_s14_receivables import _context, _negotiation


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _issue(client, store, headers, actor, customer, product):
    negotiation = await _negotiation(client, store, headers, actor, customer, product, uuid.uuid4().hex)
    response = await client.post(f"/api/v1/receivables/negotiations/{negotiation['id']}/issue", headers={
        **headers, "Idempotency-Key": f"issue-{uuid.uuid4()}",
    }, json={"customer_id": customer["id"], "expected_version": negotiation["version"], "reason": "Crédito autorizado", "actor_id": actor})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_s15_partial_receipt_and_agreement_preserve_originals_and_idempotency():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers, actor, customer, product = await _context(client, "Collection")
        policy = await client.put(f"/api/v1/receivables/customers/{customer['id']}/policy", headers=headers, json={
            "credit_limit": 500, "terms_days": 30, "status": "ACTIVE", "actor_id": actor,
        })
        assert policy.status_code == 200
        first = await _issue(client, store, headers, actor, customer, product)
        settlement_key = f"settlement-{uuid.uuid4()}"
        command = {
            "allocations": [{
                "receivable_id": first["id"], "expected_version": first["version"],
                "principal_amount": 30, "interest_amount": 2, "fine_amount": 1,
                "discount_amount": 1, "abatement_amount": 0,
            }],
            "method": "PIX", "provider_reference": "PIX-E2E-S15",
            "reason": "Liquidação parcial autorizada", "actor_id": actor,
        }
        settled = await client.post("/api/v1/receivables/settlements", headers={
            **headers, "Idempotency-Key": settlement_key,
        }, json=command)
        assert settled.status_code == 200, settled.text
        assert float(settled.json()["amount"]) == 32
        retry = await client.post("/api/v1/receivables/settlements", headers={
            **headers, "Idempotency-Key": settlement_key,
        }, json=command)
        assert retry.status_code == 200 and retry.json()["id"] == settled.json()["id"]
        remaining_first = next(item for item in (await client.get("/api/v1/receivables", headers=headers)).json() if item["id"] == first["id"])
        assert float(remaining_first["balance"]) == 30
        assert float(remaining_first["principal_amount"]) == 60

        second = await _issue(client, store, headers, actor, customer, product)
        agreement_key = f"agreement-{uuid.uuid4()}"
        agreement = await client.post("/api/v1/receivables/agreements", headers={
            **headers, "Idempotency-Key": agreement_key,
        }, json={
            "receivable_ids": [first["id"], second["id"]], "installment_count": 3,
            "first_due_at": (datetime.utcnow() + timedelta(days=15)).isoformat(), "interval_days": 30,
            "interest_amount": 9, "fine_amount": 0, "discount_amount": 0,
            "reason": "Acordo em três parcelas", "actor_id": actor,
        })
        assert agreement.status_code == 200, agreement.text
        agreement_body = agreement.json()
        assert float(agreement_body["original_principal"]) == 90
        assert float(agreement_body["agreement_total"]) == 99
        rows = (await client.get("/api/v1/receivables", headers=headers)).json()
        originals = [item for item in rows if item["id"] in {first["id"], second["id"]}]
        assert all(item["status"] == "RENEGOTIATED" and float(item["balance"]) == 0 for item in originals)
        children = [item for item in rows if item.get("agreement_id") == agreement_body["id"]]
        assert len(children) == 3
        assert sum(float(item["principal_amount"]) for item in children) == 99

        installment = children[0]
        paid_installment = await client.post("/api/v1/receivables/settlements", headers={
            **headers, "Idempotency-Key": f"installment-{uuid.uuid4()}",
        }, json={
            "allocations": [{"receivable_id": installment["id"], "expected_version": installment["version"], "principal_amount": installment["balance"]}],
            "method": "PIX", "reason": "Primeira parcela do acordo", "actor_id": actor,
        })
        assert paid_installment.status_code == 200, paid_installment.text
        after = (await client.get("/api/v1/receivables", headers=headers)).json()
        assert next(item for item in after if item["id"] == installment["id"])["status"] == "PAID"
        assert len([item for item in after if item.get("agreement_id") == agreement_body["id"] and item["status"] == "OPEN"]) == 2

    with Session(engine) as db:
        set_platform_db_context(db)
        persisted_agreement = db.get(ReceivableAgreement, uuid.UUID(agreement_body["id"]))
        assert persisted_agreement is not None
        assert len(db.exec(select(ReceivableAgreementItem).where(ReceivableAgreementItem.agreement_id == persisted_agreement.id)).all()) == 2
        persisted_receipt = db.get(ReceivableReceipt, uuid.UUID(settled.json()["id"]))
        assert persisted_receipt is not None
        assert len(db.exec(select(ReceivableReceiptAllocation).where(ReceivableReceiptAllocation.receipt_id == persisted_receipt.id)).all()) == 1
