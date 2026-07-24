"""Async SQLAlchemy engine and session."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from incident_api.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"ssl": False},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
