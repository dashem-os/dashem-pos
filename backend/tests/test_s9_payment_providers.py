import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.provider import (
    PaymentExecutionEvent, PaymentExecutionStageEnum,
    ProviderTransaction, ProviderTransactionEvent,
)
from test_s8_checkout_negotiation import _context, _intent


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


async def _payment_binding(client, headers, actor, store_id, register_id, configuration_id, terminal_id, suffix):
    device = (await client.post("/api/v1/devices", headers=headers, json={
        "store_id": store_id, "code": f"POS-{suffix}", "name": "POS de pagamento",
        "device_type": "POS", "register_id": register_id, "actor_id": actor,
    }))
    assert device.status_code == 201, device.text
    device = device.json()
    response = await client.post("/api/v1/providers/device-bindings", headers={
        **headers, "Idempotency-Key": f"binding-{uuid.uuid4()}",
    }, json={
        "store_id": store_id, "register_id": register_id,
        "operational_device_id": device["id"], "provider_configuration_id": configuration_id,
        "execution_mode": "TEF_BRIDGE", "tef_bridge_terminal_id": terminal_id,
        "actor_id": actor,
    })
    assert response.status_code == 201, response.text
    return response.json(), device


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
        binding, _device = await _payment_binding(
            client, headers, actor, store["id"], cash["register_id"], configuration["id"], terminal["id"], "S9-01",
        )

        # The checkout browser is no longer allowed to choose a provider or
        # bridge terminal. Only the server-validated binding is accepted.
        legacy_execute = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"legacy-{uuid.uuid4()}",
        }, json={
            "payment_intent_id": card_intent["id"],
            "provider_configuration_id": configuration["id"],
            "bridge_terminal_id": terminal["id"], "actor_id": actor,
        })
        assert legacy_execute.status_code == 422

        smartpos_device = await client.post("/api/v1/devices", headers=headers, json={
            "store_id": store["id"], "code": "POS-SMARTPOS-01", "name": "SmartPOS homologação",
            "device_type": "POS", "register_id": cash["register_id"], "actor_id": actor,
        })
        assert smartpos_device.status_code == 201, smartpos_device.text
        smartpos_binding = await client.post("/api/v1/providers/device-bindings", headers={
            **headers, "Idempotency-Key": f"smartpos-{uuid.uuid4()}",
        }, json={
            "store_id": store["id"], "register_id": cash["register_id"],
            "operational_device_id": smartpos_device.json()["id"],
            "provider_configuration_id": configuration["id"], "execution_mode": "SMARTPOS",
            "external_device_reference": "SMARTPOS-HOMOLOGATION-01", "actor_id": actor,
        })
        assert smartpos_binding.status_code == 201, smartpos_binding.text
        smartpos_execute = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"smartpos-exec-{uuid.uuid4()}",
        }, json={
            "payment_intent_id": card_intent["id"],
            "payment_device_binding_id": smartpos_binding.json()["id"], "actor_id": actor,
        })
        assert smartpos_execute.status_code == 409
        assert "adapter homologado" in smartpos_execute.json()["detail"]

        execute_key = f"tef-{uuid.uuid4()}"
        execute_payload = {
            "payment_intent_id": card_intent["id"],
            "payment_device_binding_id": binding["id"], "actor_id": actor,
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
        assert result["transaction"]["payment_device_binding_id"] == binding["id"]
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

        paused = await client.patch(f"/api/v1/providers/device-bindings/{binding['id']}", headers=headers, json={
            "status": "PAUSED", "reason": "Manutenção programada do terminal", "actor_id": actor,
        })
        assert paused.status_code == 200, paused.text
        assert paused.json()["status"] == "PAUSED"
        blocked_after_pause = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"paused-{uuid.uuid4()}",
        }, json={
            "payment_intent_id": card_intent["id"],
            "payment_device_binding_id": binding["id"], "actor_id": actor,
        })
        assert blocked_after_pause.status_code == 409

        _tenant_b, _store_b, headers_b, actor_b, *_ = await _context(client, "TefOther")
        assert (await client.get("/api/v1/providers/configurations", headers=headers_b)).json() == []
        assert (await client.get("/api/v1/providers/device-bindings", headers=headers_b)).json() == []
        foreign_binding = await client.patch(f"/api/v1/providers/device-bindings/{binding['id']}", headers=headers_b, json={
            "status": "PAUSED", "reason": "Tentativa entre tenants", "actor_id": actor_b,
        })
        assert foreign_binding.status_code == 404
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
        authority_events = db.exec(select(PaymentExecutionEvent).where(
            PaymentExecutionEvent.provider_transaction_id == transactions[0].id,
        ).order_by(PaymentExecutionEvent.sequence)).all()
        assert [event.stage for event in authority_events[:2]] == [
            PaymentExecutionStageEnum.REQUESTED, PaymentExecutionStageEnum.APPROVED,
        ]
        assert sum(event.stage == PaymentExecutionStageEnum.EXECUTED for event in authority_events) == 1
        assert authority_events[-1].stage == PaymentExecutionStageEnum.RESULT_RECORDED
        assert authority_events[-1].outcome == "CONFIRMED"


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
        binding, _device = await _payment_binding(
            client, headers, actor, store["id"], cash["register_id"], configuration["id"], paired["terminal"]["id"], "S9-02",
        )
        offline = await client.post("/api/v1/providers/transactions", headers={
            **headers, "Idempotency-Key": f"offline-{uuid.uuid4()}",
        }, json={
            "payment_intent_id": card["id"], "payment_device_binding_id": binding["id"], "actor_id": actor,
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
