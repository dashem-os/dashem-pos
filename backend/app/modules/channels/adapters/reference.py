"""Conector de referência — o canal simulado com que o S10.1 se prova.

Existe só em teste e desenvolvimento (o registro não o entrega em outro
ambiente). Sucede o `ContractTestChannelAdapter` do S10 e usa o mesmo código de
provedor, `CONTRACT_TEST`, para que conexões de teste já existentes continuem
sendo dele.

O formato é deste conector e de nenhum canal real: um corpo JSON com `events`,
assinado por HMAC-SHA256 **sobre os bytes recebidos**, no cabeçalho
`X-Dashem-Reference-Signature: sha256=<hex>`. O segredo é derivado de
`SECRET_KEY` só porque este conector não sai de teste; canal real verifica com a
credencial do aplicativo na plataforma (§3.3).

Nenhuma rejeição carrega o que foi recebido: o motivo é um código, e a exceção
de conversão original é descartada (`from None`) para que nem a cadeia de
exceções leve o valor a um log (H17).
"""

import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional

from app.core.config import settings
from app.modules.channels.contracts import (
    ChannelCapability, DeliveryOutcome, DeliveryResult, ExternalContact, ExternalEvent,
    ExternalEventKind, ExternalOrder, ExternalOrderLine, IngressEnvelope, OutboundNotice,
    PayloadRejected, SignatureRejected, ValidationOutcome,
)


PROVIDER_CODE = "CONTRACT_TEST"
PARSER_VERSION = "reference-1"
SIGNATURE_HEADER = "X-Dashem-Reference-Signature"
FULFILLMENTS = {"DELIVERY", "TAKEAWAY", "COUNTER"}


def _secret() -> bytes:
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), b"channel-reference-ingress", hashlib.sha256).digest()


def sign(body: bytes) -> str:
    """The header value this connector expects for `body`. Used by the tests that play the channel."""
    return "sha256=" + hmac.new(_secret(), body, hashlib.sha256).hexdigest()


def _text(value, code: str, *, required: bool = True) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise PayloadRejected(code)
        return None
    if not isinstance(value, (str, int)):
        raise PayloadRejected(code)
    return str(value).strip()


def _amount(value, code: str) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PayloadRejected(code) from None
    if not amount.is_finite() or amount < 0:
        raise PayloadRejected(code)
    return amount


def _mapping(value, code: str) -> Mapping:
    if not isinstance(value, dict):
        raise PayloadRejected(code)
    return value


class ReferenceChannelAdapter:
    provider_code = PROVIDER_CODE
    parser_version = PARSER_VERSION
    capabilities = frozenset({
        ChannelCapability.CONNECTION_VALIDATION,
        ChannelCapability.ORDER_INGRESS,
        ChannelCapability.ORDER_EVENTS,
        ChannelCapability.ORDER_STATUS_OUTBOUND,
    })

    # O canal simulado deduplica pelo identificador do aviso (E4). Vocabulário de
    # avisos deste conector, e de nenhum canal real.
    idempotent_delivery = True
    supported_notice_types = frozenset({
        "ORDER_ACCEPTED", "ORDER_READY", "ORDER_DISPATCHED", "ORDER_CONCLUDED", "ORDER_CANCELLED",
    })

    def send_notice(self, notice: OutboundNotice) -> DeliveryOutcome:
        if notice.message_type not in self.supported_notice_types:
            return DeliveryOutcome(DeliveryResult.PERMANENT, code="NOTICE_TYPE_NOT_SUPPORTED")
        return DeliveryOutcome(DeliveryResult.DELIVERED, provider_reference=f"ref-{notice.notice_id}")

    def confirm_notice(self, notice: OutboundNotice):
        return True

    def validate_connection(self, merchant_external_id: str) -> ValidationOutcome:
        if merchant_external_id and merchant_external_id.strip():
            return ValidationOutcome(connected=True)
        return ValidationOutcome(connected=False, code="MERCHANT_MISSING")

    def verify_signature(self, headers: Mapping[str, str], body: bytes) -> None:
        received = next(
            (value for name, value in headers.items() if name.lower() == SIGNATURE_HEADER.lower()),
            None,
        )
        if not received:
            raise SignatureRejected("SIGNATURE_MISSING")
        if not hmac.compare_digest(received, sign(body)):
            raise SignatureRejected("SIGNATURE_INVALID")

    def envelopes(self, body: bytes) -> tuple[IngressEnvelope, ...]:
        try:
            document = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise PayloadRejected("BODY_NOT_JSON") from None
        events = document.get("events") if isinstance(document, dict) else None
        if not isinstance(events, list) or not events:
            raise PayloadRejected("EVENTS_MISSING")
        envelopes = []
        for raw in events:
            event = _mapping(raw, "EVENT_INVALID")
            envelopes.append(IngressEnvelope(
                provider_event_id=_text(event.get("id"), "EVENT_ID_MISSING"),
                merchant_external_id=_text(event.get("merchant_id"), "MERCHANT_MISSING"),
                event_type=_text(event.get("type"), "EVENT_TYPE_MISSING"),
                payload=event,
                external_order_id=_text(event.get("order_id"), "ORDER_ID_INVALID", required=False),
            ))
        return tuple(envelopes)

    def normalize(self, envelope: IngressEnvelope) -> ExternalEvent:
        event = envelope.payload
        try:
            kind = ExternalEventKind(envelope.event_type)
        except ValueError:
            raise PayloadRejected("EVENT_TYPE_UNKNOWN") from None
        external_order_id = _text(event.get("order_id"), "ORDER_ID_MISSING")
        occurred_at = None
        if event.get("occurred_at") is not None:
            try:
                occurred_at = datetime.fromisoformat(str(event["occurred_at"]))
            except ValueError:
                raise PayloadRejected("OCCURRED_AT_INVALID") from None
        sequence = event.get("sequence")
        if sequence is not None and (not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0):
            raise PayloadRejected("SEQUENCE_INVALID")
        order_key = f"{sequence:020d}" if sequence is not None else (
            occurred_at.isoformat() if occurred_at is not None else None
        )
        order = None
        if kind in {ExternalEventKind.ORDER_PLACED, ExternalEventKind.ORDER_UPDATED}:
            order = self._order(external_order_id, _mapping(event.get("order"), "ORDER_MISSING"))
        return ExternalEvent(
            provider_event_id=envelope.provider_event_id, kind=kind,
            external_order_id=external_order_id, order_key=order_key,
            occurred_at=occurred_at, parser_version=self.parser_version,
            order=order, contact=self._contact(event.get("customer")),
        )

    def _order(self, external_order_id: str, order: Mapping) -> ExternalOrder:
        fulfillment = _text(order.get("fulfillment"), "FULFILLMENT_MISSING").upper()
        if fulfillment not in FULFILLMENTS:
            raise PayloadRejected("FULFILLMENT_UNSUPPORTED")
        raw_lines = order.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise PayloadRejected("LINES_MISSING")
        lines = []
        for raw in raw_lines:
            line = _mapping(raw, "LINE_INVALID")
            quantity = _amount(line.get("quantity"), "LINE_QUANTITY_INVALID")
            if quantity is None or quantity <= 0:
                raise PayloadRejected("LINE_QUANTITY_INVALID")
            modifiers = line.get("modifiers") or []
            if not isinstance(modifiers, list):
                raise PayloadRejected("LINE_MODIFIERS_INVALID")
            lines.append(ExternalOrderLine(
                external_line_id=_text(line.get("id"), "LINE_ID_MISSING"),
                external_item_code=_text(line.get("item_code"), "LINE_ITEM_CODE_MISSING"),
                quantity=quantity,
                unit_amount=_amount(line.get("unit_price"), "LINE_AMOUNT_INVALID"),
                discount_amount=_amount(line.get("discount"), "LINE_AMOUNT_INVALID"),
                modifier_codes=tuple(_text(code, "LINE_MODIFIERS_INVALID") for code in modifiers),
                preparation_notes=_text(line.get("notes"), "LINE_NOTES_INVALID", required=False),
            ))
        payment = order.get("payment") if isinstance(order.get("payment"), dict) else {}
        return ExternalOrder(
            external_order_id=external_order_id, fulfillment=fulfillment, lines=tuple(lines),
            delivery_fee=_amount(order.get("delivery_fee"), "ORDER_AMOUNT_INVALID"),
            channel_discount=_amount(order.get("discount"), "ORDER_AMOUNT_INVALID"),
            channel_subsidy=_amount(order.get("subsidy"), "ORDER_AMOUNT_INVALID"),
            declared_total=_amount(order.get("total"), "ORDER_AMOUNT_INVALID"),
            payment_origin="MARKETPLACE" if payment.get("status") == "PAID_ONLINE" else None,
        )

    @staticmethod
    def _contact(customer) -> ExternalContact:
        if customer is None:
            return ExternalContact()
        customer = _mapping(customer, "CUSTOMER_INVALID")
        address = customer.get("address")
        if address is not None and not isinstance(address, dict):
            raise PayloadRejected("CUSTOMER_ADDRESS_INVALID")
        return ExternalContact(
            display_name=_text(customer.get("name"), "CUSTOMER_INVALID", required=False),
            phone=_text(customer.get("phone"), "CUSTOMER_INVALID", required=False),
            delivery_address=address or None,
            delivery_instructions=_text(customer.get("instructions"), "CUSTOMER_INVALID", required=False),
        )
