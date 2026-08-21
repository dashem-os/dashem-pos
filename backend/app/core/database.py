from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

def init_db() -> None:
    SQLModel.metadata.create_all(engine)
