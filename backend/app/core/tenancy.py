"""Database-enforced request context for tenant and site isolation.

The values are transaction-local PostgreSQL settings. RLS policies deny rows
when no appropriate context is present, so forgetting an ORM filter cannot
turn into a cross-tenant or cross-site disclosure.
"""

import uuid
from typing import Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import Session


CONTEXT_INFO_KEY = "dashem_db_context"


def _apply_context(connection, values: dict[str, str]) -> None:
    connection.execute(
        text("""SELECT
            set_config('app.platform_access', :platform_access, true),
            set_config('app.tenant_id', :tenant_id, true),
            set_config('app.store_id', :store_id, true),
            set_config('app.user_id', :user_id, true)
        """),
        values,
    )


@event.listens_for(OrmSession, "after_begin")
def _restore_context_after_commit(session, _transaction, connection) -> None:
    """A service may commit mid-request; the next transaction remains scoped."""
    values = session.info.get(CONTEXT_INFO_KEY)
    if values:
        _apply_context(connection, values)


def _set_context(session: Session, **updates: Optional[str]) -> None:
    values = {
        "platform_access": "false",
        "tenant_id": "",
        "store_id": "",
        "user_id": "",
        **session.info.get(CONTEXT_INFO_KEY, {}),
    }
    values.update({key: value or "" for key, value in updates.items()})
    session.info[CONTEXT_INFO_KEY] = values
    # Start/apply now; after_begin restores the same values after every commit.
    session.exec(text("SELECT 1"))
    _apply_context(session.connection(), values)


def set_user_db_context(session: Session, user_id: Optional[uuid.UUID]) -> None:
    _set_context(session, user_id=str(user_id) if user_id else None)


def set_tenant_db_context(
    session: Session,
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
) -> None:
    _set_context(
        session,
        platform_access="false",
        tenant_id=str(tenant_id),
        store_id=str(store_id) if store_id else None,
        user_id=str(user_id) if user_id else None,
    )


def set_platform_db_context(session: Session, user_id: Optional[uuid.UUID] = None) -> None:
    """Open cross-tenant visibility only after platform RBAC has succeeded."""
    _set_context(
        session,
        tenant_id=None,
        store_id=None,
        user_id=str(user_id) if user_id else None,
        platform_access="true",
    )
