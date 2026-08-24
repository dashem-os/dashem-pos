import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.fiscal import FiscalDocument, FiscalEvent, FiscalEventTypeEnum
from app.models.reconciliation import FinancialReconciliation, ReconciliationEvent
from test_s14_receivables import _context
from test_s15_receivable_collection import _issue


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


@pytest.mark.asyncio
async def test_s16_cash_two_phase_reconciliation_and_fiscal_retry_are_non_destructive():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers, actor, customer, product = await _context(client, "Reconciliation")
        register = await client.post("/api/v1/cash/registers", headers=headers, json={
            "store_id": store["id"], "name": "Caixa S16", "code": f"S16-{uuid.uuid4().hex[:6]}",
        })
        assert register.status_code == 200, register.text
        opened = await client.post("/api/v1/cash/sessions/open", headers=headers, json={
            "store_id": store["id"], "register_id": register.json()["id"],
            "operator_id": actor, "opening_balance": 100,
        })
        assert opened.status_code == 200, opened.text
        cash_id = opened.json()["id"]
        for movement_type, amount in (("REINFORCEMENT", 20), ("BLEED", 5)):
            movement = await client.post(f"/api/v1/cash/sessions/{cash_id}/movements", headers=headers, json={
                "actor_id": actor, "movement_type": movement_type, "amount": amount,
                "notes": f"Movimento de prova {movement_type}",
            })
            assert movement.status_code == 200, movement.text
        beginning = await client.post(f"/api/v1/cash/sessions/{cash_id}/begin-close", headers=headers, json={
            "operator_id": actor, "expected_version": 1, "blind_count": True,
        })
        assert beginning.status_code == 200 and beginning.json()["status"] == "CLOSING"
        duplicate_begin = await client.post(f"/api/v1/cash/sessions/{cash_id}/begin-close", headers=headers, json={
            "operator_id": actor, "expected_version": 1, "blind_count": True,
        })
        assert duplicate_begin.status_code == 409
        closed = await client.post(f"/api/v1/cash/sessions/{cash_id}/finalize-close", headers=headers, json={
            "operator_id": actor, "expected_version": beginning.json()["version"], "closing_balance": 115,
        })
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "CLOSED"
        assert float(closed.json()["expected_balance"]) == 115
        assert float(closed.json()["variance"]) == 0

        policy = await client.put(f"/api/v1/receivables/customers/{customer['id']}/policy", headers=headers, json={
            "credit_limit": 500, "terms_days": 30, "status": "ACTIVE", "actor_id": actor,
        })
        assert policy.status_code == 200
        receivable = await _issue(client, store, headers, actor, customer, product)
        sale_id = receivable["sale_id"]
        sale_before = await client.get(f"/api/v1/sales/{sale_id}", headers=headers)
        assert sale_before.status_code == 200
        difference = await client.post(f"/api/v1/reconciliations/sales/{sale_id}", headers=headers, json={
            "actor_id": actor, "provider_reported_total": 59, "provider": "ACQUIRER-S16",
            "provider_reference": "BATCH-001", "notes": "Arquivo externo divergente",
        })
        assert difference.status_code == 200, difference.text
        assert difference.json()["status"] == "DIFFERENCE"
        assert float(difference.json()["difference"]) == -1
        matched = await client.post(f"/api/v1/reconciliations/sales/{sale_id}", headers=headers, json={"actor_id": actor})
        assert matched.status_code == 200, matched.text
        assert matched.json()["id"] == difference.json()["id"]
        assert matched.json()["version"] == difference.json()["version"] + 1
        assert matched.json()["status"] == "MATCHED"
        sale_after = await client.get(f"/api/v1/sales/{sale_id}", headers=headers)
        assert sale_after.json()["status"] == sale_before.json()["status"]

        rejected = await client.post("/api/v1/fiscal/documents/issue", headers=headers, json={
            "sale_id": sale_id, "actor_id": actor, "document_type": "NFCE", "simulate_status": "REJECTED",
        })
        assert rejected.status_code == 200, rejected.text
        document = rejected.json()["fiscal_document"]
        assert document["status"] == "REJECTED" and document["attempt_count"] == 1
        retried = await client.post(f"/api/v1/fiscal/documents/{document['id']}/retry", headers=headers, json={
            "actor_id": actor,
        })
        assert retried.status_code == 200, retried.text
        assert retried.json()["id"] == document["id"]
        assert retried.json()["status"] == "AUTHORIZED"
        assert retried.json()["attempt_count"] == 2

    with Session(engine) as db:
        set_platform_db_context(db)
        assert len(db.exec(select(FinancialReconciliation).where(FinancialReconciliation.sale_id == uuid.UUID(sale_id))).all()) == 1
        record = db.exec(select(FinancialReconciliation).where(FinancialReconciliation.sale_id == uuid.UUID(sale_id))).one()
        assert len(db.exec(select(ReconciliationEvent).where(ReconciliationEvent.reconciliation_id == record.id)).all()) == 2
        assert len(db.exec(select(FiscalDocument).where(FiscalDocument.sale_id == uuid.UUID(sale_id))).all()) == 1
        events = db.exec(select(FiscalEvent).where(FiscalEvent.fiscal_document_id == uuid.UUID(document["id"]))).all()
        assert any(event.event_type == FiscalEventTypeEnum.RETRY_REQUESTED for event in events)
