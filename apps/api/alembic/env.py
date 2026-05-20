"""Alembic env.py — async-capable migration runner.

Reads the database URL from app Settings (respects .env / environment variables)
and uses SQLAlchemy's async engine so the asyncpg driver is used throughout;
no psycopg2 install required.
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Make app importable when alembic is invoked from apps/api/ ────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.database import Base  # noqa: E402

# Import every model module so SQLAlchemy registers their tables in metadata.
import app.models.bar            # noqa: F401, E402
import app.models.decision_log   # noqa: F401, E402
import app.models.fill           # noqa: F401, E402
import app.models.instrument     # noqa: F401, E402
import app.models.order          # noqa: F401, E402
import app.models.position       # noqa: F401, E402
import app.models.risk_event     # noqa: F401, E402
import app.models.strategy       # noqa: F401, E402

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# Override the URL from alembic.ini with the one from Settings.
alembic_config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


# ── Offline mode (generates SQL without connecting) ───────────────────────────

def run_migrations_offline() -> None:
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (connects to the real database) ───────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
