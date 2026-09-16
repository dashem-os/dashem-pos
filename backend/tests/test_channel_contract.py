"""S10.1, step 1: the channel contract, before any of it touches the database.

Proposal `docs/product/proposta-s10-1-channel-hub.md`, §3.2. These tests hold
the promises the rest of S10.1 builds on:

- an adapter is called only for what it declares, and the reference connector
  exists only in test and development (H11);
- a signature is checked over the bytes received — the same JSON, re-serialized,
  is a different message (R16);
- a rejection is a code and nothing else: no fragment of what arrived, not even
  through the exception chain (H17, P9);
- the order never carries the person; the contact does (H13).

Everything here is the simulated channel. Nothing proves anything about a real
provider.
"""

import dataclasses
import json
from decimal import Decimal

import pytest

from app.core.config import settings
from app.modules.channels import registry
from app.modules.channels.adapters import reference
from app.modules.channels.contracts import (
    CapabilityNotDeclared, ChannelCapability, ChannelRejection, ExternalContact,
    ExternalEventKind, ExternalOrder, ExternalOrderLine, PayloadRejected, SignatureRejected,
    require,
)

MARKER = "MARCADOR-PESSOAL-5511999990000"
PERSONAL_TOKENS = {"name", "nome", "phone", "telefone", "address", "endereco", "instructions", "customer"}


def _event(**overrides) -> dict:
    event = {
        "id": "evt-1", "merchant_id": "loja-1", "type": "ORDER_PLACED",
        "order_id": "pedido-1", "sequence": 7, "occurred_at": "2026-09-16T12:00:00",
        "order": {
            "fulfillment": "delivery",
            "lines": [{"id": "l1", "item_code": "SKU-1", "quantity": "2", "unit_price": "10.50",
                       "discount": "0.50", "modifiers": ["M1"], "notes": "sem cebola"}],
            "delivery_fee": "5.00", "discount": "1.00", "subsidy": "0", "total": "25.00",
            "payment": {"status": "PAID_ONLINE"},
        },
        "customer": {"name": "Ana", "phone": "11999990000",
                     "address": {"street": "Rua A", "number": "10"}, "instructions": "portão azul"},
    }
    event.update(overrides)
    return event


def _body(*events) -> bytes:
    return json.dumps({"events": list(events)}).encode("utf-8")


def _rejection_is_only_a_code(error: ChannelRejection) -> None:
    assert MARKER not in str(error)
    assert MARKER not in repr(error.args)
    # Nada da exceção de conversão original sobrevive na cadeia.
    assert error.__cause__ is None
    assert error.__suppress_context__ or error.__context__ is None


def test_the_reference_connector_exists_only_in_test_and_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    assert isinstance(registry.adapter_for("contract_test"), reference.ReferenceChannelAdapter)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    adapter = registry.adapter_for("CONTRACT_TEST")
    assert adapter.capabilities == frozenset()
    assert isinstance(registry.adapter_for("IFOOD"), registry.UnavailableChannelAdapter)


def test_a_capability_that_was_never_declared_is_refused_not_called():
    unavailable = registry.UnavailableChannelAdapter("IFOOD")
    with pytest.raises(CapabilityNotDeclared) as error:
        require(unavailable, ChannelCapability.ORDER_INGRESS)
    assert error.value.capability == ChannelCapability.ORDER_INGRESS
    connector = reference.ReferenceChannelAdapter()
    require(connector, ChannelCapability.ORDER_INGRESS)
    with pytest.raises(CapabilityNotDeclared):
        require(connector, ChannelCapability.CATALOG_PUBLICATION)


def test_the_signature_is_over_the_bytes_that_arrived():
    connector = reference.ReferenceChannelAdapter()
    body = _body(_event())
    connector.verify_signature({"x-dashem-reference-signature": reference.sign(body)}, body)

    same_content = json.dumps(json.loads(body), indent=2, sort_keys=True).encode("utf-8")
    assert json.loads(same_content) == json.loads(body)
    with pytest.raises(SignatureRejected) as reserialized:
        connector.verify_signature({reference.SIGNATURE_HEADER: reference.sign(body)}, same_content)
    assert reserialized.value.code == "SIGNATURE_INVALID"
    with pytest.raises(SignatureRejected) as missing:
        connector.verify_signature({}, body)
    assert missing.value.code == "SIGNATURE_MISSING"


def test_a_body_splits_into_events_each_with_its_merchant():
    connector = reference.ReferenceChannelAdapter()
    envelopes = connector.envelopes(_body(_event(), _event(id="evt-2", merchant_id="loja-2")))
    assert [(e.provider_event_id, e.merchant_external_id, e.event_type) for e in envelopes] == [
        ("evt-1", "loja-1", "ORDER_PLACED"), ("evt-2", "loja-2", "ORDER_PLACED"),
    ]


@pytest.mark.parametrize(("body", "code"), [
    (b"nao e json " + MARKER.encode(), "BODY_NOT_JSON"),
    (json.dumps({"eventos": [MARKER]}).encode(), "EVENTS_MISSING"),
    (_body({"merchant_id": MARKER, "type": "ORDER_PLACED"}), "EVENT_ID_MISSING"),
    (_body({"id": "e", "type": "ORDER_PLACED", "customer": {"name": MARKER}}), "MERCHANT_MISSING"),
])
def test_a_rejected_body_leaves_only_a_code(body, code):
    with pytest.raises(PayloadRejected) as error:
        reference.ReferenceChannelAdapter().envelopes(body)
    assert error.value.code == code
    _rejection_is_only_a_code(error.value)


@pytest.mark.parametrize(("event", "code"), [
    (_event(type="PEDIDO_" + MARKER), "EVENT_TYPE_UNKNOWN"),
    (_event(occurred_at=MARKER), "OCCURRED_AT_INVALID"),
    (_event(order={**_event()["order"], "fulfillment": MARKER}), "FULFILLMENT_UNSUPPORTED"),
    (_event(order={**_event()["order"], "lines": [{"id": "l", "item_code": "S", "quantity": MARKER}]}), "LINE_QUANTITY_INVALID"),
    (_event(order={**_event()["order"], "total": MARKER}), "ORDER_AMOUNT_INVALID"),
    (_event(customer={"name": "Ana", "address": MARKER}), "CUSTOMER_ADDRESS_INVALID"),
])
def test_a_rejected_event_leaves_only_a_code(event, code):
    connector = reference.ReferenceChannelAdapter()
    envelope = connector.envelopes(_body(event))[0]
    with pytest.raises(PayloadRejected) as error:
        connector.normalize(envelope)
    assert error.value.code == code
    _rejection_is_only_a_code(error.value)


def test_the_order_never_carries_the_person_and_the_contact_does():
    for kind in (ExternalOrder, ExternalOrderLine):
        fields = {part for f in dataclasses.fields(kind) for part in f.name.split("_")}
        assert fields.isdisjoint(PERSONAL_TOKENS), f"{kind.__name__} tem campo pessoal"

    connector = reference.ReferenceChannelAdapter()
    event = connector.normalize(connector.envelopes(_body(_event()))[0])
    assert event.kind == ExternalEventKind.ORDER_PLACED
    assert event.parser_version == reference.PARSER_VERSION
    assert event.order_key == "00000000000000000007"
    assert event.order.fulfillment == "DELIVERY"
    assert event.order.payment_origin == "MARKETPLACE"
    assert event.order.declared_total == Decimal("25.00")
    line = event.order.lines[0]
    assert (line.external_line_id, line.external_item_code, line.quantity) == ("l1", "SKU-1", Decimal("2"))
    assert (line.unit_amount, line.discount_amount, line.modifier_codes) == (Decimal("10.50"), Decimal("0.50"), ("M1",))
    assert event.contact == ExternalContact(
        display_name="Ana", phone="11999990000",
        delivery_address={"street": "Rua A", "number": "10"}, delivery_instructions="portão azul",
    )
    serialized_order = json.dumps(dataclasses.asdict(event.order), default=str)
    for personal in ("Ana", "11999990000", "Rua A", "portão azul"):
        assert personal not in serialized_order


def test_an_event_without_a_customer_has_an_empty_contact_and_a_cancellation_needs_no_order():
    connector = reference.ReferenceChannelAdapter()
    cancelled = _event(type="ORDER_CANCELLED")
    cancelled.pop("order"); cancelled.pop("customer"); cancelled.pop("sequence")
    event = connector.normalize(connector.envelopes(_body(cancelled))[0])
    assert event.kind == ExternalEventKind.ORDER_CANCELLED
    assert event.order is None and event.contact.is_empty()
    assert event.order_key == "2026-09-16T12:00:00"
