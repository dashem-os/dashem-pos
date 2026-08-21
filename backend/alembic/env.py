import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from sqlmodel import SQLModel

# Import all models to ensure metadata is populated
from app.models import Tenant, Store, User, Membership, OutboxEvent, AuditEvent, IdempotencyRecord
from app.core.config import settings

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

def get_url():
    return os.getenv("DATABASE_URL", settings.DATABASE_URL)

def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        run_migrations_online()

def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    if configuration is None:
        configuration = {}
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
