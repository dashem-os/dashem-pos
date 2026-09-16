"""What a channel adapter promises, capability by capability.

S10.1 proposal, §3.2. There is no adapter obliged to do everything: each one
declares what it can do, and a capability it does not declare is never called —
its absence is a state the screen shows, not an exception somebody catches (H11).

The normalized types are channel-agnostic, and they keep the customer apart from
the order on purpose (H13). `ExternalOrder` carries identifiers, lines and the
amounts the channel declared; `ExternalContact` carries the name, phone, address
and delivery instructions. They are stored in different layers with different
retention (§3.7), and nothing downstream should be able to reach the person by
holding only the order.

Rejections carry a **code**, never a fragment of what was received. A quarantine
reason and a log line are built from these, and neither may hold personal data
(H17).
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional, Protocol


class ChannelCapability(str, Enum):
    CONNECTION_VALIDATION = "CONNECTION_VALIDATION"
    ORDER_INGRESS = "ORDER_INGRESS"
    ORDER_EVENTS = "ORDER_EVENTS"
    ORDER_STATUS_OUTBOUND = "ORDER_STATUS_OUTBOUND"
    # S13.2 — declared in the contract now, implemented there.
    CATALOG_PUBLICATION = "CATALOG_PUBLICATION"
    AVAILABILITY = "AVAILABILITY"
    SETTLEMENT_IMPORT = "SETTLEMENT_IMPORT"


class ExternalEventKind(str, Enum):
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_UPDATED = "ORDER_UPDATED"
    ORDER_CONCLUDED = "ORDER_CONCLUDED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class ChannelRejection(Exception):
    """Something received could not be accepted. The message is the code, and only the code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SignatureRejected(ChannelRejection):
    pass


class PayloadRejected(ChannelRejection):
    pass


class CapabilityNotDeclared(LookupError):
    def __init__(self, provider_code: str, capability: ChannelCapability) -> None:
        super().__init__(f"{provider_code} não declara {capability.value}")
        self.provider_code = provider_code
        self.capability = capability


@dataclass(frozen=True)
class IngressEnvelope:
    """One event as it arrived, before anything is interpreted.

    Only what the server needs to persist and route it: the channel's event id,
    the merchant it belongs to, the event type as the channel wrote it, and the
    raw content of that event. Normalization happens later, from the stored raw
    content, so a failure there never costs the event.
    """

    provider_event_id: str
    merchant_external_id: str
    event_type: str
    payload: Mapping
    # Para agrupar eventos do mesmo pedido já na chegada; ausente não impede persistir.
    external_order_id: Optional[str] = None


class ChannelDataPermission(str, Enum):
    """D7: one permission per action over channel personal data and its retention.

    They exist in the permission catalog (migration 098) and are **granted to no
    profile**. No route requires or offers them until the grant is defined and
    tested; `test_channel_ingress` fails if any profile or person receives one
    before that.
    """

    ORDER_CONTACT_READ = "channel.order_contact.read"
    LEGAL_HOLD_MANAGE = "channel.legal_hold.manage"
    RETENTION_EXTEND = "channel.retention.extend"
    RETENTION_PURGE = "channel.retention.purge"


@dataclass(frozen=True)
class ExternalOrderLine:
    external_line_id: str
    external_item_code: str
    quantity: Decimal
    unit_amount: Optional[Decimal]
    discount_amount: Optional[Decimal]
    modifier_codes: tuple[str, ...] = ()
    # Instrução de preparo ("sem cebola"). Segue para a cozinha; é texto livre e
    # pode trazer dado pessoal por acidente — limite declarado em §3.7.2.
    preparation_notes: Optional[str] = None


@dataclass(frozen=True)
class ExternalOrder:
    """The order as the channel declared it. No field here names a person."""

    external_order_id: str
    fulfillment: str
    lines: tuple[ExternalOrderLine, ...]
    delivery_fee: Optional[Decimal] = None
    channel_discount: Optional[Decimal] = None
    channel_subsidy: Optional[Decimal] = None
    declared_total: Optional[Decimal] = None
    payment_origin: Optional[str] = None


@dataclass(frozen=True)
class ExternalContact:
    """The person behind the order, kept apart from it (H13)."""

    display_name: Optional[str] = None
    phone: Optional[str] = None
    delivery_address: Optional[Mapping] = None
    delivery_instructions: Optional[str] = None

    def is_empty(self) -> bool:
        return not any((self.display_name, self.phone, self.delivery_address, self.delivery_instructions))


@dataclass(frozen=True)
class ExternalEvent:
    provider_event_id: str
    kind: ExternalEventKind
    external_order_id: str
    # Chave de ordem declarada pelo adaptador: sequência do canal, ou o instante
    # do evento. Comparável como texto de largura fixa (§3.4, H5).
    order_key: Optional[str]
    occurred_at: Optional[datetime]
    parser_version: str
    order: Optional[ExternalOrder] = None
    contact: ExternalContact = field(default_factory=ExternalContact)


@dataclass(frozen=True)
class ValidationOutcome:
    connected: bool
    code: Optional[str] = None


class DeliveryResult(str, Enum):
    """What the channel said about one notice.

    `AMBIGUOUS` is neither success nor failure: the call timed out or broke after
    it may have arrived. What happens next depends on whether the channel
    deduplicates by the notice identity (E4) or has to be asked (E5).
    """

    DELIVERED = "DELIVERED"
    RETRYABLE = "RETRYABLE"
    PERMANENT = "PERMANENT"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class OutboundNotice:
    """One notice to a channel. `notice_id` is stable: resending repeats it."""

    notice_id: str
    merchant_external_id: str
    external_order_id: str
    message_type: str
    payload: Mapping


@dataclass(frozen=True)
class DeliveryOutcome:
    result: DeliveryResult
    provider_reference: Optional[str] = None
    code: Optional[str] = None


class ChannelAdapter(Protocol):
    provider_code: str
    parser_version: str
    capabilities: frozenset


class ConnectionValidation(Protocol):
    def validate_connection(self, merchant_external_id: str) -> ValidationOutcome: ...


class OrderIngress(Protocol):
    def verify_signature(self, headers: Mapping[str, str], body: bytes) -> None:
        """Raise `SignatureRejected` unless `body` — the bytes as received — is signed."""
        ...

    def envelopes(self, body: bytes) -> tuple[IngressEnvelope, ...]:
        """Split a verified body into events. Raise `PayloadRejected` with a code."""
        ...

    def normalize(self, envelope: IngressEnvelope) -> ExternalEvent:
        """Interpret one stored event. Raise `PayloadRejected` with a code."""
        ...


class OrderStatusOutbound(Protocol):
    # E4: the channel deduplicates a resent notice by its identity.
    idempotent_delivery: bool
    supported_notice_types: frozenset

    def send_notice(self, notice: OutboundNotice) -> DeliveryOutcome:
        """Send once. A code in the outcome, never a fragment of what was sent."""
        ...

    def confirm_notice(self, notice: OutboundNotice) -> Optional[bool]:
        """E5: did this notice arrive? True, False, or None when the channel cannot say."""
        ...


def require(adapter: ChannelAdapter, capability: ChannelCapability) -> None:
    """Refuse to call what the adapter never declared (H11)."""
    if capability not in adapter.capabilities:
        raise CapabilityNotDeclared(adapter.provider_code, capability)
