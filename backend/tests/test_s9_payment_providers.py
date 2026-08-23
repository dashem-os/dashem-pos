import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.provider import ProviderTransaction, ProviderTransactionEvent
from test_s8_checkout_negotiation import _context, _intent


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


@pytest.mark.asyncio
async def test_s9_bridge_unknown_retry_and_authenticated_result_confirm_only_its_intent():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store, headers, actor, _table, table_session, _order_id, cash = await _context(client, "Tef")
        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "table_session_id": table_session["id"], "actor_id": actor})).json()
        _, cash_intent = await _intent(client, headers, negotiation["id"], actor, "CASH", 10, uuid.uuid4(), cash["id"])
        cash_confirmed = await client.post(f"/api/v1/negotiations/intents/{cash_intent['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"cash-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert cash_confirmed.status_code == 200
        _, card_intent = await _intent(client, headers, negotiation["id"], actor, "CREDIT_CARD", 54.9, uuid.uuid4())

        empty = await client.get("/api/v1/providers/bridge/terminals", headers=headers, params={"register_id": cash["register_id"]})
        assert empty.status_code == 200 and empty.json() == []
        configuration = (await client.post("/api/v1/providers/configurations", headers={**headers, "Idempotency-Key": f"config-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "provider_code": "SITEF",
            "credentials_ref": "secret://tenant/sitef-homologation", "actor_id": actor,
        })).json()
        assert "credentials_ref" not in configuration
        paired = (await client.post("/api/v1/providers/bridge/terminals", headers={**headers, "Idempotency-Key": f"pair-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "register_id": cash["register_id"],
            "provider_configuration_id": configuration["id"], "terminal_code": "PINPAD-01", "actor_id": actor,
        })).json()
        terminal, pairing_code = paired["terminal"], paired["pairing_code"]
        assert "pairing_secret_hash" not in terminal
        heartbeat = await client.post(f"/api/v1/providers/bridge/terminals/{terminal['id']}/heartbeat", json={
            "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": pairing_code,
            "bridge_version": "1.0.0", "protocol_version": "1.0",
        })
        assert heartbeat.status_code == 200, heartbeat.text
        assert heartbeat.json()["status"] == "ONLINE"

        execute_key = f"tef-{uuid.uuid4()}"
        execute_payload = {
            "payment_intent_id": card_intent["id"],
            "provider_configuration_id": configuration["id"],
            "bridge_terminal_id": terminal["id"], "actor_id": actor,
        }
        started = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": execute_key, "X-Correlation-ID": f"corr-{uuid.uuid4()}",
        }, json=execute_payload)
        assert started.status_code == 200, started.text
        started_body = started.json()
        assert started_body["transaction"]["status"] == "PROCESSING"
        assert float(started_body["negotiation"]["confirmed_amount"]) == 10

        retry = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": execute_key,
        }, json=execute_payload)
        assert retry.status_code == 200
        assert retry.json()["transaction"]["id"] == started_body["transaction"]["id"]
        assert retry.json()["transaction"]["status"] == "UNKNOWN"
        assert float(retry.json()["negotiation"]["confirmed_amount"]) == 10

        bad_report = await client.post(
            f"/api/v1/providers/bridge/terminals/{terminal['id']}/transactions/{started_body['transaction']['id']}/result",
            json={
                "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": "invalid-pairing-code-with-length",
                "status": "CONFIRMED", "external_transaction_id": "SITEF-123",
            },
        )
        assert bad_report.status_code == 401
        reported = await client.post(
            f"/api/v1/providers/bridge/terminals/{terminal['id']}/transactions/{started_body['transaction']['id']}/result",
            json={
                "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": pairing_code,
                "status": "CONFIRMED", "external_transaction_id": "SITEF-123",
                "nsu": "000123456", "authorization_code": "A12345",
                "acquirer": "ACQUIRER", "card_brand": "VISA",
            },
        )
        assert reported.status_code == 200, reported.text
        result = reported.json()
        assert result["transaction"]["status"] == "CONFIRMED"
        assert result["transaction"]["nsu"] == "000123456"
        assert result["negotiation"]["status"] == "COVERED"
        assert float(result["negotiation"]["confirmed_amount"]) == 64.9
        report_retry = await client.post(
            f"/api/v1/providers/bridge/terminals/{terminal['id']}/transactions/{started_body['transaction']['id']}/result",
            json={
                "tenant_id": tenant["id"], "store_id": store["id"], "pairing_code": pairing_code,
                "status": "CONFIRMED", "external_transaction_id": "SITEF-123", "nsu": "000123456",
            },
        )
        assert report_retry.status_code == 200
        assert float(report_retry.json()["negotiation"]["confirmed_amount"]) == 64.9

        _tenant_b, _store_b, headers_b, *_ = await _context(client, "TefOther")
        assert (await client.get("/api/v1/providers/configurations", headers=headers_b)).json() == []
        hidden = await client.post(f"/api/v1/providers/transactions/{started_body['transaction']['id']}/reconcile", headers=headers_b, json={"actor_id": actor})
        assert hidden.status_code == 404

    with Session(engine) as db:
        set_platform_db_context(db)
        transactions = db.exec(select(ProviderTransaction).where(
            ProviderTransaction.payment_intent_id == uuid.UUID(card_intent["id"]),
        )).all()
        assert len(transactions) == 1
        events = db.exec(select(ProviderTransactionEvent).where(
            ProviderTransactionEvent.provider_transaction_id == transactions[0].id,
        )).all()
        assert {event.event_type for event in events} >= {"payment.provider.started", "payment.provider.result"}


@pytest.mark.asyncio
async def test_s9_offline_tef_does_not_block_local_payment_methods():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        _tenant, store, headers, actor, _table, table_session, _order_id, cash = await _context(client, "Offline")
        negotiation = (await client.post("/api/v1/negotiations", headers={
            **headers, "Idempotency-Key": f"neg-{uuid.uuid4()}",
        }, json={"store_id": store["id"], "table_session_id": table_session["id"], "actor_id": actor})).json()
        _, card = await _intent(client, headers, negotiation["id"], actor, "DEBIT_CARD", 20, uuid.uuid4())
        configuration = (await client.post("/api/v1/providers/configurations", headers={**headers, "Idempotency-Key": f"config-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "provider_code": "PAYGO", "credentials_ref": "secret://paygo", "actor_id": actor,
        })).json()
        paired = (await client.post("/api/v1/providers/bridge/terminals", headers={**headers, "Idempotency-Key": f"pair-{uuid.uuid4()}"}, json={
            "store_id": store["id"], "register_id": cash["register_id"],
            "provider_configuration_id": configuration["id"], "terminal_code": "OFFLINE-01", "actor_id": actor,
        })).json()
        offline = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"offline-{uuid.uuid4()}",
        }, json={
            "payment_intent_id": card["id"], "provider_configuration_id": configuration["id"],
            "bridge_terminal_id": paired["terminal"]["id"], "actor_id": actor,
        })
        assert offline.status_code == 503
        failed_release = await client.post(f"/api/v1/negotiations/intents/{card['id']}/fail", headers={
            **headers, "Idempotency-Key": f"offline-fail-{uuid.uuid4()}",
        }, json={"actor_id": actor, "failure_code": "BRIDGE_OFFLINE", "reason": "Bridge indisponível"})
        assert failed_release.status_code == 200
        _, pix = await _intent(client, headers, negotiation["id"], actor, "PIX", 64.9, uuid.uuid4())
        confirmed = await client.post(f"/api/v1/negotiations/intents/{pix['id']}/confirm", headers={
            **headers, "Idempotency-Key": f"pix-{uuid.uuid4()}",
        }, json={"actor_id": actor})
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "COVERED"
