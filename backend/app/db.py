"""
数据库连接 (Async database)
===========================

对应 Lecture 6「Layered architecture」中的**系统数据库层**。
本文件只负责：建引擎、建会话、提供依赖注入用的 session。

业务代码不直接碰引擎 —— 这样从 SQLite 换成 PostgreSQL 时，
只需要改 config.database_url（ADR-001 的收益）。
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_settings = get_settings()

# SQLite 需要确保目录存在
if _settings.database_url.startswith("sqlite"):
    _path = _settings.database_url.split("///")[-1]
    _dir = os.path.dirname(os.path.abspath(_path))
    os.makedirs(_dir, exist_ok=True)

# SQLite 用 NullPool：测试里每个事件循环独立，避免连接被跨循环复用。
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
    """FastAPI 依赖：每个请求一个会话。"""
    async with SessionLocal() as session:
        yield session
