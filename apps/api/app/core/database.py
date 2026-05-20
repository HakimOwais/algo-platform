import asyncio
import logging
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    """Boot-time DB initialisation.

    Production: run `alembic upgrade head` before starting the server.
    The server itself never calls create_all — schema changes are managed
    exclusively through Alembic migrations.

    Development shortcut: set APP_ENV=development to auto-apply pending
    migrations at startup via a subprocess call (avoids a separate shell
    step when iterating locally; disabled in prod/staging).
    """
    import app.models.bar          # noqa: F401
    import app.models.decision_log # noqa: F401
    import app.models.fill         # noqa: F401
    import app.models.instrument   # noqa: F401
    import app.models.order        # noqa: F401
    import app.models.position     # noqa: F401
    import app.models.risk_event   # noqa: F401
    import app.models.strategy     # noqa: F401

    settings = get_settings()
    if settings.app_env == "development":
        await _run_alembic_upgrade()


async def _run_alembic_upgrade() -> None:
    """Run `alembic upgrade head` in a subprocess (development only).

    Using a subprocess avoids nested asyncio event loop issues that arise
    when calling alembic's programmatic API (which internally calls
    asyncio.run) from inside an asyncio.to_thread context.
    """
    alembic_dir = Path(__file__).resolve().parents[2]

    def _run() -> None:
        result = subprocess.run(
            ["python", "-m", "alembic", "upgrade", "head"],
            cwd=str(alembic_dir),
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            logger.info("[alembic] %s", line)
        if result.returncode != 0:
            logger.error("[alembic] %s", result.stderr)
            raise RuntimeError(f"alembic upgrade head failed (exit {result.returncode})")

    await asyncio.to_thread(_run)
