from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


@lru_cache
def get_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker(database_url: str) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(database_url), expire_on_commit=False)


async def get_db_session(settings: SettingsDep) -> AsyncGenerator[AsyncSession]:
    sessionmaker = get_sessionmaker(settings.database_url)
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


async def init_database(settings: Settings) -> None:
    """Create tables for all imported ORM models."""
    import patients.orm  # noqa: F401

    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ping_database(settings: Settings) -> bool:
    engine = get_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


async def close_database(database_url: str) -> None:
    engine = get_engine(database_url)
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
