"""Module."""
from __future__ import annotations
import os
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from .config import get_settings
class Base(DeclarativeBase):
    """Base."""
_settings = get_settings()
if _settings.database_url.startswith("sqlite"):
    _path = _settings.database_url.split("///")[-1]
    _dir = os.path.dirname(os.path.abspath(_path))
    os.makedirs(_dir, exist_ok=True)
engine = create_async_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    future=True,
    poolclass=NullPool if _settings.is_sqlite else None,
)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
async def get_session() -> AsyncIterator[AsyncSession]:
    """Get session."""
    async with SessionLocal() as session:
        yield session
