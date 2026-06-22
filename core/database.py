from collections.abc import AsyncGenerator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Protocol, cast

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
DATABASE_INIT_SQL = Path(__file__).resolve().parent.parent / "database" / "init.sql"


class _SqlScriptExecutor(Protocol):
    async def execute(
        self,
        query: str,
        *args: object,
        timeout: float | None = None,
    ) -> str: ...


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


async def ping_database(settings: Settings) -> bool:
    engine = get_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


async def init_database(settings: Settings) -> None:
    sql = DATABASE_INIT_SQL.read_text(encoding="utf-8")
    engine = get_engine(settings.database_url)
    async with engine.begin() as connection:
        raw_connection = await connection.get_raw_connection()
        driver_connection = cast(_SqlScriptExecutor, raw_connection.driver_connection)
        await driver_connection.execute(sql)


async def close_database(database_url: str) -> None:
    engine = get_engine(database_url)
    await engine.dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
