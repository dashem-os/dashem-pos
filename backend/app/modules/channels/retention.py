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

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, or_
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


def _no_hold_in_force(model, observed: datetime):
    return or_(model.legal_hold_until.is_(None), model.legal_hold_until <= observed)


def deadline_summary(
    session: Session, tenant_id: uuid.UUID, store_id: Optional[uuid.UUID] = None, *, now: Optional[datetime] = None,
) -> dict:
    """What can be said about deadlines today: counts and instants, nothing personal (H20).

    - **awaiting terminal**: orders whose clocks have not started, because the
      order has not ended yet;
    - **overdue**: a deadline that passed, content still there, no legal hold in
      force. There is no purge, so "overdue" is never "removed": it is waiting
      for a cleanup that does not exist yet.
    """
    observed = now or datetime.utcnow()

    def scoped(model, *conditions):
        conditions = (model.tenant_id == tenant_id, *conditions)
        return conditions + ((model.store_id == store_id,) if store_id else ())

    awaiting, awaiting_since = session.exec(select(
        func.count(ExternalOrderMapping.id), func.min(ExternalOrderMapping.created_at),
    ).where(*scoped(ExternalOrderMapping, ExternalOrderMapping.terminal_at.is_(None)))).one()
    events, events_since = session.exec(select(
        func.count(ChannelInboxEvent.id), func.min(ChannelInboxEvent.retention_until),
    ).where(*scoped(
        ChannelInboxEvent, ChannelInboxEvent.retention_until <= observed,
        _no_hold_in_force(ChannelInboxEvent, observed),
    ))).one()
    contacts, contacts_since = session.exec(select(
        func.count(ChannelOrderContact.id), func.min(ChannelOrderContact.retention_until),
    ).where(*scoped(
        ChannelOrderContact, ChannelOrderContact.retention_until <= observed,
        ChannelOrderContact.redacted_at.is_(None), _no_hold_in_force(ChannelOrderContact, observed),
    ))).one()
    overdue_since = min((at for at in (events_since, contacts_since) if at is not None), default=None)
    return {
        "measured_at": observed,
        "orders_awaiting_terminal": int(awaiting or 0),
        "oldest_awaiting_terminal_created_at": awaiting_since if awaiting else None,
        "overdue_events": int(events or 0),
        "overdue_contacts": int(contacts or 0),
        "oldest_overdue_until": overdue_since,
        # Said in the data, so no screen concludes more than exists: no cleanup
        # has ever run because there is no cleanup yet.
        "cleanup_exists": False,
        "last_cleanup_at": None,
    }


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
