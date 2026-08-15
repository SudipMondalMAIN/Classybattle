"""
Async SQLAlchemy engine + session factory.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import settings

_engine_kwargs: dict = {"echo": settings.DB_ECHO, "pool_pre_ping": True}

_USING_TRANSACTION_POOLER = ":6543" in settings.DATABASE_URL

if _USING_TRANSACTION_POOLER:
    # PgBouncer (Supabase Transaction Pooler, port 6543) already pools
    # connections on the DB side, and in transaction mode it can hand a
    # client a *different* physical backend connection on every
    # transaction. Layering SQLAlchemy's own client-side pool on top of
    # that breaks asyncpg's prepared-statement bookkeeping: a pooled
    # asyncpg Connection keeps its own statement counter (__asyncpg_stmt_N__)
    # across transactions, but PgBouncer may attach it to a backend that
    # already has a statement with that same auto-generated name left
    # over from a different client -- causing random
    # "prepared statement ... already exists / does not exist" errors.
    #
    # Fix: disable asyncpg's statement cache AND use NullPool so
    # SQLAlchemy opens a fresh asyncpg connection per checkout instead of
    # reusing one across transactions. PgBouncer is the pool now.
    _engine_kwargs["connect_args"] = {"statement_cache_size": 0}
    _engine_kwargs["poolclass"] = NullPool
elif not settings.DATABASE_URL.startswith("sqlite"):
    # SQLite (local/dev testing) doesn't support pool_size/max_overflow.
    _engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session and guarantees cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()