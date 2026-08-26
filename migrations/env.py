"""Alembic environment — resolves the URL from DATABASE_URL (converting the
async driver to its sync twin) and targets the engine's metadata."""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from engine.config import get_settings
from engine.db import Base
from engine import models  # noqa: F401 — populate metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    """Map whatever DATABASE_URL form we're given (Render's driverless
    postgres://, the app's postgresql+asyncpg://, sqlite+aiosqlite://) to the
    sync driver Alembic runs on (psycopg2 / built-in sqlite)."""
    url = os.environ.get("DATABASE_URL") or get_settings().database_url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    url = url.replace("+asyncpg", "").replace("+aiosqlite", "")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
