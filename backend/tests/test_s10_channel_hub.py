import hashlib
import hmac
import json
import os
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import ExternalOrderMapping
from app.models.negotiation import PaymentIntent
from app.models.order import Order, OrderItem
from app.models.provider import ProviderTransaction


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")


def _signature(secret: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _base(client: httpx.AsyncClient, prefix: str):
    suffix = uuid.uuid4().hex[:8]; actor = str(uuid.uuid4())
    tenant = (await client.post("/api/v1/identity/tenants", json={"name": prefix, "slug": f"{prefix.lower()}-{suffix}"})).json()
    store = (await client.post("/api/v1/identity/stores", json={"tenant_id": tenant["id"], "name": "Matriz", "code": f"CH-{suffix}"})).json()
    with Session(engine) as db:
        set_platform_db_context(db)
        from app.models.platform import TenantCapability, EntitlementStatusEnum
        db.add(TenantCapability(
            tenant_id=uuid.UUID(tenant["id"]),
            key="delivery_orders",
            enabled=True,
            status=EntitlementStatusEnum.ACTIVE,
        ))
        db.commit()
    headers = {"X-Tenant-ID": tenant["id"], "X-Store-ID": store["id"]}
    product = (await client.post("/api/v1/catalog/products", headers=headers, json={
        "name": "Produto canal", "sku": f"CH-{suffix}", "unit": "UN", "tracks_inventory": False,
        "requires_fulfillment": True, "production_destination": "COZINHA",
    })).json()
    await client.post("/api/v1/catalog/prices", headers=headers, json={
        "product_id": product["id"], "store_id": store["id"], "cost_price": 5, "sale_price": 18.5,
    })
    await client.post("/api/v1/catalog/assortments", headers=headers, json={
        "code": f"ASSORT-DELIV-{suffix}",
        "name": "Sortimento Delivery",
        "scopes": [{"store_id": store["id"], "sales_context": "DELIVERY"}],
        "product_ids": [product["id"]],
    })
    key = f"connection-{uuid.uuid4()}"
    connection_payload = {
        "store_id": store["id"], "provider_code": "CONTRACT_TEST",
        "merchant_external_id": f"merchant-{suffix}", "channel_name": "Canal de contrato",
        "credentials_ref": "secret://channel-contract", "actor_id": actor,
    }
    created = await client.post("/api/v1/channels/connections", headers={**headers, "Idempotency-Key": key}, json=connection_payload)
    assert created.status_code == 200, created.text
    retry = await client.post("/api/v1/channels/connections", headers={**headers, "Idempotency-Key": key}, json=connection_payload)
    assert retry.status_code == 200
    assert retry.json()["webhook_secret"] == created.json()["webhook_secret"]
    connection = created.json()["connection"]; secret = created.json()["webhook_secret"]
    assert "credentials_ref" not in connection and "webhook_secret_hash" not in connection
    validation_key = f"validate-{uuid.uuid4()}"
    validated = await client.post(f"/api/v1/channels/connections/{connection['id']}/validate", headers={
        **headers, "Idempotency-Key": validation_key,
    }, json={"actor_id": actor})
    assert validated.status_code == 200 and validated.json()["status"] == "CONNECTED"
    validation_retry = await client.post(f"/api/v1/channels/connections/{connection['id']}/validate", headers={
        **headers, "Idempotency-Key": validation_key,
    }, json={"actor_id": actor})
    assert validation_retry.status_code == 200 and validation_retry.json()["id"] == connection["id"]
    return tenant, store, headers, actor, product, connection, secret


@pytest.mark.asyncio
async def test_s10_durable_inbox_deduplicates_into_canonical_order_and_quarantines_invalid_payload():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        tenant, store, headers, actor, product, connection, secret = await _base(client, "Channel")
        payload = {
            "external_order_id": f"external-{uuid.uuid4()}", "fulfillment": "DELIVERY",
            "customer_name": "Cliente externo", "notes": "Sem contato",
            "payment": {"status": "PAID_ONLINE", "provider": "MARKETPLACE"},
            "items": [{"product_id": product["id"], "quantity": 2, "notes": "Bem passado"}],
        }
        event_id = f"evt-{uuid.uuid4()}"
        webhook = {
            "tenant_id": tenant["id"], "store_id": store["id"], "connection_id": connection["id"],
            "provider_event_id": event_id, "event_type": "ORDER_CREATED", "payload": payload,
            "signature": _signature(secret, payload),
        }
        accepted = await client.post("/api/v1/channels/webhooks", json=webhook)
        assert accepted.status_code == 200, accepted.text
        event = accepted.json()
        assert event["status"] == "PROCESSED", f"Event quarantined: {event.get('quarantine_reason')}"
        assert event["acknowledged_at"] is not None
        assert event["order_id"] is not None
        order = (await client.get(f"/api/v1/orders/{event['order_id']}", headers=headers)).json()
        assert order["origin"] == "SALES_CHANNEL"
        assert order["fulfillment"] == "DELIVERY"
        assert order["channel_id"] == connection["channel_id"]
        assert len(order["items"]) == 1 and float(order["items"][0]["quantity"]) == 2

        replay = await client.post("/api/v1/channels/webhooks", json=webhook)
        assert replay.status_code == 200
        assert replay.json()["id"] == event["id"]
        same_order_new_event = {**webhook, "provider_event_id": f"evt-{uuid.uuid4()}"}
        duplicate = await client.post("/api/v1/channels/webhooks", json=same_order_new_event)
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "DUPLICATE"
        assert duplicate.json()["order_id"] == event["order_id"]

        outbound_key = f"out-{uuid.uuid4()}"
        outbound = await client.post(f"/api/v1/channels/orders/{event['order_id']}/outbound", headers={
            **headers, "Idempotency-Key": outbound_key,
        }, json={"message_type": "ORDER_ACCEPTED", "payload": {"status": "ACCEPTED"}, "actor_id": actor})
        assert outbound.status_code == 200
        assert outbound.json()["status"] == "PENDING"
        outbound_retry = await client.post(f"/api/v1/channels/orders/{event['order_id']}/outbound", headers={
            **headers, "Idempotency-Key": outbound_key,
        }, json={"message_type": "ORDER_ACCEPTED", "payload": {"status": "ACCEPTED"}, "actor_id": actor})
        assert outbound_retry.json()["id"] == outbound.json()["id"]

        invalid_payload = {
            "external_order_id": f"invalid-{uuid.uuid4()}", "fulfillment": "DELIVERY",
            "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
        }
        quarantined = await client.post("/api/v1/channels/webhooks", json={
            "tenant_id": tenant["id"], "store_id": store["id"], "connection_id": connection["id"],
            "provider_event_id": f"bad-{uuid.uuid4()}", "event_type": "ORDER_CREATED",
            "payload": invalid_payload, "signature": _signature(secret, invalid_payload),
        })
        assert quarantined.status_code == 200
        assert quarantined.json()["status"] == "QUARANTINED"
        assert quarantined.json()["order_id"] is None

        _tenant_b, _store_b, headers_b, *_ = await _base(client, "OtherChannel")
        assert all(item["id"] != connection["id"] for item in (await client.get("/api/v1/channels/connections", headers=headers_b)).json())
        assert all(item["id"] != event["id"] for item in (await client.get("/api/v1/channels/inbox", headers=headers_b)).json())

    with Session(engine) as db:
        set_platform_db_context(db)
        orders = db.exec(select(Order).where(Order.id == uuid.UUID(event["order_id"]))).all()
        items = db.exec(select(OrderItem).where(OrderItem.order_id == uuid.UUID(event["order_id"]))).all()
        mapping = db.exec(select(ExternalOrderMapping).where(ExternalOrderMapping.order_id == uuid.UUID(event["order_id"]))).one()
        provider_transactions = db.exec(select(ProviderTransaction).where(ProviderTransaction.tenant_id == uuid.UUID(tenant["id"]))).all()
        payment_intents = db.exec(select(PaymentIntent).where(PaymentIntent.tenant_id == uuid.UUID(tenant["id"]))).all()
        assert len(orders) == 1 and len(items) == 1
        assert mapping.payment_origin == "MARKETPLACE"
        assert provider_transactions == [] and payment_intents == []
