"""S10 through the S10.1 door: a channel order lands in the same Order Engine.

Rewritten on 16/09/2026, when `/channels/webhooks` left (S10.1, step 3). What S10
proved still holds and is proved again here, through the ingress by provider:
the external order becomes a canonical `Order` of origin `SALES_CHANNEL`, a
repeated event creates nothing, an event that cannot be applied is kept in
quarantine with no order, one tenant never sees another's connections or events,
and a marketplace-paid order creates no payment and no TEF transaction.

The channel is the reference connector; every answer it gives is simulated.
"""

import json
import os
import time
import uuid

import httpx
import pytest
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.channel_hub import ChannelInboxEvent, ExternalOrderMapping
from app.models.negotiation import PaymentIntent
from app.models.order import Order, OrderItem
from app.models.provider import ProviderTransaction
from app.modules.channels.adapters import reference


BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
INGRESS = "/api/v1/channels/ingress/CONTRACT_TEST"
WAITING = {"RECEIVED", "PROCESSING"}


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
        "actor_id": actor,
    }
    created = await client.post("/api/v1/channels/connections", headers={**headers, "Idempotency-Key": key}, json=connection_payload)
    assert created.status_code == 200, created.text
    retry = await client.post("/api/v1/channels/connections", headers={**headers, "Idempotency-Key": key}, json=connection_payload)
    assert retry.status_code == 200
    assert retry.json()["connection"]["id"] == created.json()["connection"]["id"]
    connection = created.json()["connection"]
    # Nenhum segredo por conexão: o canal assina com a credencial do aplicativo.
    assert set(created.json()) == {"connection"}
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
    return tenant, store, headers, actor, product, connection


async def _map_item(client, headers, actor, connection, product, code: str) -> None:
    mapped = await client.post("/api/v1/channel-catalog/mappings", headers={
        **headers, "Idempotency-Key": f"map-{uuid.uuid4()}",
    }, json={"connection_id": connection["id"], "entity_type": "PRODUCT",
             "internal_id": product["id"], "external_id": code, "actor_id": actor})
    assert mapped.status_code == 200, mapped.text


async def _send(client, *events) -> httpx.Response:
    body = json.dumps({"events": list(events)}).encode("utf-8")
    return await client.post(INGRESS, content=body, headers={
        "Content-Type": "application/json", reference.SIGNATURE_HEADER: reference.sign(body),
    })


def _settled(provider_event_id: str, timeout: float = 15.0) -> ChannelInboxEvent:
    """Processing runs right after the response; wait for it to leave the queue."""
    deadline = time.monotonic() + timeout
    while True:
        with Session(engine) as db:
            set_platform_db_context(db)
            row = db.exec(select(ChannelInboxEvent).where(
                ChannelInboxEvent.provider_event_id == provider_event_id,
            )).first()
        if row is not None and row.status.value not in WAITING:
            return row
        assert time.monotonic() < deadline, f"evento {provider_event_id} não saiu da fila"
        time.sleep(0.3)


@pytest.mark.asyncio
async def test_s10_durable_inbox_deduplicates_into_canonical_order_and_quarantines_invalid_payload():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tenant, store, headers, actor, product, connection = await _base(client, "Channel")
        await _map_item(client, headers, actor, connection, product, "ITEM-CANAL-1")
        placed = {
            "id": f"evt-{uuid.uuid4()}", "merchant_id": connection["merchant_external_id"],
            "type": "ORDER_PLACED", "order_id": f"external-{uuid.uuid4()}",
            "order": {
                "fulfillment": "DELIVERY",
                "lines": [{"id": "l1", "item_code": "ITEM-CANAL-1", "quantity": 2, "notes": "Bem passado"}],
                "payment": {"status": "PAID_ONLINE"},
            },
            "customer": {"name": "Cliente externo"},
        }
        accepted = await _send(client, placed)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["events"][0]["outcome"] == "RECEIVED"
        event = _settled(placed["id"])
        assert event.status.value == "APPLIED", f"evento parou em {event.status.value}: {event.quarantine_code}"
        assert event.acknowledged_at is not None and event.order_id is not None
        order = (await client.get(f"/api/v1/orders/{event.order_id}", headers=headers)).json()
        assert order["origin"] == "SALES_CHANNEL"
        assert order["fulfillment"] == "DELIVERY"
        assert order["channel_id"] == connection["channel_id"]
        assert len(order["items"]) == 1 and float(order["items"][0]["quantity"]) == 2
        assert order["notes"] is None, "o nome do cliente não vai para as observações do pedido"

        replay = await _send(client, placed)
        assert replay.json()["events"][0]["outcome"] == "DUPLICATE"
        same_order_new_event = {**placed, "id": f"evt-{uuid.uuid4()}", "type": "ORDER_UPDATED"}
        assert (await _send(client, same_order_new_event)).json()["events"][0]["outcome"] == "RECEIVED"
        update = _settled(same_order_new_event["id"])
        assert update.status.value == "APPLIED" and update.order_id == event.order_id

        outbound_key = f"out-{uuid.uuid4()}"
        outbound = await client.post(f"/api/v1/channels/orders/{event.order_id}/outbound", headers={
            **headers, "Idempotency-Key": outbound_key,
        }, json={"message_type": "ORDER_ACCEPTED", "payload": {"status": "ACCEPTED"}, "actor_id": actor})
        assert outbound.status_code == 200
        assert outbound.json()["status"] == "PENDING"
        outbound_retry = await client.post(f"/api/v1/channels/orders/{event.order_id}/outbound", headers={
            **headers, "Idempotency-Key": outbound_key,
        }, json={"message_type": "ORDER_ACCEPTED", "payload": {"status": "ACCEPTED"}, "actor_id": actor})
        assert outbound_retry.json()["id"] == outbound.json()["id"]

        invalid = {
            "id": f"bad-{uuid.uuid4()}", "merchant_id": connection["merchant_external_id"],
            "type": "ORDER_PLACED", "order_id": f"invalid-{uuid.uuid4()}",
            "order": {"fulfillment": "DELIVERY", "lines": [{"id": "l1", "item_code": "SEM-MAPEAMENTO", "quantity": 1}]},
        }
        assert (await _send(client, invalid)).status_code == 200
        quarantined = _settled(invalid["id"])
        assert quarantined.status.value == "QUARANTINED"
        assert quarantined.quarantine_code == "ITEM_NOT_MAPPED"
        assert quarantined.order_id is None

        _tenant_b, _store_b, headers_b, *_ = await _base(client, "OtherChannel")
        assert all(item["id"] != connection["id"] for item in (await client.get("/api/v1/channels/connections", headers=headers_b)).json())
        assert all(item["id"] != str(event.id) for item in (await client.get("/api/v1/channels/inbox", headers=headers_b)).json())

    with Session(engine) as db:
        set_platform_db_context(db)
        orders = db.exec(select(Order).where(Order.id == event.order_id)).all()
        items = db.exec(select(OrderItem).where(OrderItem.order_id == event.order_id)).all()
        mapping = db.exec(select(ExternalOrderMapping).where(ExternalOrderMapping.order_id == event.order_id)).one()
        provider_transactions = db.exec(select(ProviderTransaction).where(ProviderTransaction.tenant_id == uuid.UUID(tenant["id"]))).all()
        payment_intents = db.exec(select(PaymentIntent).where(PaymentIntent.tenant_id == uuid.UUID(tenant["id"]))).all()
        assert len(orders) == 1 and len(items) == 1
        assert mapping.payment_origin == "MARKETPLACE"
        assert provider_transactions == [] and payment_intents == []
