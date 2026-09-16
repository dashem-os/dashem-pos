"""What the bridge's own routes do with the database.

Every function takes the scope of a terminal that already authenticated and
never trusts anything else to say whose data it is.

The long poll calls `claim` many times while it waits, so `claim` and `touch`
open a session each, commit and close it: no transaction stays open and no
connection stays checked out between attempts (§3.12). With a pool of ten and a
synchronous driver, a bridge waiting on a held connection would be a bridge
taking the sale's connection away.
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.database import engine
from app.core.tenancy import set_tenant_db_context
from app.models.provider import TefBridgeTerminal
from app.modules.finance.bridge import commands
from app.modules.finance.bridge.credentials import TerminalScope
from app.modules.finance.bridge.models import TefBridgeCommand


def _scoped(session: Session, scope: TerminalScope) -> None:
    set_tenant_db_context(session, scope.tenant_id, scope.store_id, None)


def command_body(command: TefBridgeCommand) -> dict:
    return {
        "id": command.id,
        "command_type": command.command_type,
        "command_class": command.command_class,
        "sequence": command.sequence,
        "provider_transaction_id": command.provider_transaction_id,
        "installation_epoch": command.installation_epoch,
        "attempts": command.attempts,
        "lease_expires_at": command.available_at,
        "correlation_id": command.correlation_id,
        "payload": command.payload,
    }


def command_state(command: TefBridgeCommand) -> dict:
    return {
        "id": command.id,
        "delivery_status": command.delivery_status,
        "closed_reason": command.closed_reason,
    }


def touch(scope: TerminalScope) -> None:
    """The bridge spoke. Presence, not readiness: the pinpad may still be off."""
    with Session(engine) as session:
        _scoped(session, scope)
        terminal = session.get(TefBridgeTerminal, scope.terminal_id)
        if terminal is not None:
            terminal.last_seen_at = datetime.utcnow()
            session.add(terminal)
            session.commit()


def claim(scope: TerminalScope) -> Optional[dict]:
    """One attempt at handing this terminal its next command."""
    with Session(engine) as session:
        _scoped(session, scope)
        command = commands.claim_next(session, terminal_id=scope.terminal_id)
        body = command_body(command) if command is not None else None
        session.commit()
        return body


def owned_command(session: Session, scope: TerminalScope, command_id: uuid.UUID) -> TefBridgeCommand:
    """The command, if it was addressed to this terminal — locked for the answer.

    A command of another terminal is not "forbidden": for this bridge it does
    not exist, and saying otherwise would confirm an identifier it should not
    know.
    """
    _scoped(session, scope)
    command = session.exec(select(TefBridgeCommand).where(
        TefBridgeCommand.id == command_id,
        TefBridgeCommand.bridge_terminal_id == scope.terminal_id,
    ).with_for_update()).first()
    if command is None:
        raise HTTPException(status_code=404, detail="Comando não pertence a este bridge.")
    return command


def ack(session: Session, scope: TerminalScope, command_id: uuid.UUID) -> dict:
    command = owned_command(session, scope, command_id)
    commands.ack_command(session, command)
    state = command_state(command)
    session.commit()
    return state
