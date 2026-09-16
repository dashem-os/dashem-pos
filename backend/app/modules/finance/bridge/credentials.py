"""Who is speaking for a paired terminal.

A bridge carries no user session. It proves itself with the credential issued at
pairing, and everything it may touch is derived from the terminal that
credential opens — never from what the request body claims. Until 16/09/2026
the heartbeat and the result callback set the database scope from the body and
only then authenticated (finding A5 of the transport proposal).
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlmodel import Session

from app.core.database import engine
from app.core.tenancy import set_platform_db_context
from app.models.provider import TefBridgeTerminal


def hash_credential(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def matches(terminal: TefBridgeTerminal, credential: str) -> bool:
    return secrets.compare_digest(terminal.pairing_secret_hash, hash_credential(credential))


@dataclass(frozen=True)
class TerminalScope:
    terminal_id: uuid.UUID
    tenant_id: uuid.UUID
    store_id: uuid.UUID


def authenticate(terminal_id: uuid.UUID, credential: str) -> TerminalScope:
    """Open the terminal with its credential and say whose it is.

    The lookup cannot be tenant-scoped, because the tenant is what it finds out.
    Like principal resolution in `app.core.access`, it reads with platform
    visibility in a session of its own, answers this one question and closes.
    Nothing it saw reaches the caller's session, which is then scoped to the
    tenant and unit of the terminal that authenticated.
    """
    with Session(engine) as session:
        set_platform_db_context(session)
        terminal = session.get(TefBridgeTerminal, terminal_id)
        if terminal is None or not credential or not matches(terminal, credential):
            raise HTTPException(status_code=401, detail="Credencial local do bridge inválida.")
        return TerminalScope(terminal.id, terminal.tenant_id, terminal.store_id)
