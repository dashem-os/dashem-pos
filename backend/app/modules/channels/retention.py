"""When channel data stops being kept — política técnica inicial, not legal advice.

S10.1 proposal §3.7, D3 approved and D6 decided by the owner on 16/09/2026.
These numbers are an **initial technical policy** to build and test against.
They are not legal guidance, they declare no compliance, and they are not a
commercial promise: before any of that they need validation by whoever answers
for legal and privacy (G1).

What this module does today is assign deadlines. Nothing here removes data —
the purge is a later step, and until it exists and the provider's backup cycle
is documented, retention is not "implemented".

One rule runs through all of it: **a deadline, once assigned, only gets
shorter.** The single exception is an event applied to an order without ever
having been quarantined: it trades its reception deadline, once, for the order's
terminal state (D3). Lengthening anything else takes a legal hold or an
authorized extension, and neither exists as a route yet (D7).
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models.channel_hub import (
    ChannelInboxEvent, ChannelOrderContact, ChannelRetentionBasisEnum,
    ExternalOrderMapping, ExternalOrderTerminalStateEnum,
)

RAW_PAYLOAD_DAYS = 30
CONTACT_DAYS = 90


def raw_payload_deadline_from_reception(received_at: datetime) -> datetime:
    """D6: every event is persisted with its payload already on the clock."""
    return received_at + timedelta(days=RAW_PAYLOAD_DAYS)


def _terminal_deadline(mapping: ExternalOrderMapping, days: int) -> Optional[datetime]:
    return mapping.terminal_at + timedelta(days=days) if mapping.terminal_at else None


def settle_applied_event(event: ChannelInboxEvent, mapping: ExternalOrderMapping) -> None:
    """An event now belongs to an order. Which clock does its payload run on?

    Never held back: the order's terminal state (D3), which may not have come
    yet. Quarantined or sent to review at any point: the reception clock it
    already had, because fixing the cause does not buy more time (D6).
    """
    if event.first_quarantined_at is not None:
        return
    if event.retention_basis == ChannelRetentionBasisEnum.RECEPCAO:
        event.retention_basis = ChannelRetentionBasisEnum.ESTADO_TERMINAL
        event.retention_until = _terminal_deadline(mapping, RAW_PAYLOAD_DAYS)


def contact_deadline(mapping: ExternalOrderMapping) -> Optional[datetime]:
    return _terminal_deadline(mapping, CONTACT_DAYS)


def anchor_terminal(
    session: Session, mapping: ExternalOrderMapping,
    state: ExternalOrderTerminalStateEnum, at: datetime,
) -> bool:
    """The order became terminal: start every clock that was waiting for it.

    Only clocks that were waiting move — terminal-based rows with no deadline yet.
    A row already on the reception clock keeps it. Returns whether this call set
    the anchor; the first terminal state recorded wins.
    """
    if mapping.terminal_at is not None:
        return False
    mapping.terminal_state = state
    mapping.terminal_at = at
    waiting = session.exec(select(ChannelInboxEvent).where(
        ChannelInboxEvent.merchant_connection_id == mapping.merchant_connection_id,
        ChannelInboxEvent.external_order_id == mapping.external_order_id,
        ChannelInboxEvent.retention_basis == ChannelRetentionBasisEnum.ESTADO_TERMINAL,
        ChannelInboxEvent.retention_until.is_(None),
    )).all()
    for event in waiting:
        event.retention_until = _terminal_deadline(mapping, RAW_PAYLOAD_DAYS)
        session.add(event)
    contact = session.exec(select(ChannelOrderContact).where(
        ChannelOrderContact.external_order_mapping_id == mapping.id,
    )).first()
    if (
        contact is not None
        and contact.retention_basis == ChannelRetentionBasisEnum.ESTADO_TERMINAL
        and contact.retention_until is None
    ):
        contact.retention_until = contact_deadline(mapping)
        session.add(contact)
    session.add(mapping)
    return True
