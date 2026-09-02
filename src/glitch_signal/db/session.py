"""Async SQLModel session factory."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession  # SQLModel's session → use session.exec()

from glitch_signal.config import settings


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    cfg = settings()
    return create_async_engine(
        cfg.resolved_db_url(),
        connect_args=cfg.db_connect_args(),
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def _session_factory() -> sessionmaker:
    return sessionmaker(
        bind=_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and commits/rolls back."""
    factory = _session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

