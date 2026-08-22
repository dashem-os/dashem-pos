import re
from typing import Generator

from sqlalchemy import event
from sqlmodel import create_engine, Session
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
)

if not re.fullmatch(r"[a-z_][a-z0-9_]*", settings.RUNTIME_DB_ROLE):
    raise ValueError("RUNTIME_DB_ROLE must be a safe PostgreSQL identifier")


@event.listens_for(engine, "checkout")
def _assume_restricted_runtime_role(
    dbapi_connection, _connection_record, _connection_proxy
) -> None:
    """Re-assert restricted authority whenever a pooled connection is leased.

    PostgreSQL drivers may reset ``SET ROLE`` when returning a connection to
    the pool. A connect-only hook would therefore protect the first borrower
    but could hand later requests the schema-owner credential.
    """
    with dbapi_connection.cursor() as cursor:
        cursor.execute(f'SET ROLE "{settings.RUNTIME_DB_ROLE}"')

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
