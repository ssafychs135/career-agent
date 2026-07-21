import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # DDL은 raw SQL(op.execute)로 소유 — autogenerate 미사용


def _alembic_url() -> str:
    """마이그레이션용 SQLAlchemy URL. ALEMBIC_URL이 있으면 우선(예: 동기 psycopg),
    없으면 런타임 DATABASE_URL(asyncpg DSN)을 SQLAlchemy async 드라이버 URL로 변환."""
    explicit = os.environ.get("ALEMBIC_URL")
    if explicit:
        return explicit
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_alembic_url().replace("+asyncpg", ""),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_alembic_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
