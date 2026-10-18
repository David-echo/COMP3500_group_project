"""
应用入口 (FastAPI app)
=====================

对应 Lecture 6「Layered architecture」：本文件只做**组装**——
挂路由、注册中间件、提供启动钩子，不写业务逻辑。
"""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config as config_module
from .api import audit, auth, elections, events, results, votes
from .db import Base, engine
from .services import pubsub


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 建表（生产环境应改用 Alembic 迁移）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = config_module.get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "COMP 3500SEF 小组项目 —— 选举管理与投票系统\n\n"
            "后端: Python + FastAPI + SQLAlchemy 2.0\n"
            "数据: PostgreSQL（开发回退 SQLite）\n"
            "实时: SSE"
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for r in (auth.router, elections.router, votes.router, results.router,
              audit.router, events.router):
        app.include_router(r, prefix=settings.api_prefix)

    @app.get("/api/health", tags=["系统"])
    async def health() -> dict:
        """健康检查：数据库可用性 + 审计链状态。"""
        from sqlalchemy import select

        from .db import SessionLocal
        from .models import AuditLog
        from .services import audit as audit_svc

        async with SessionLocal() as s:
            ok, bad, msg, tip = await audit_svc.verify(s)
            n = (await s.execute(select(AuditLog))).scalars().all()
        return {
            "status": "ok",
            "database": settings.database_url.split("://")[0],
            "redis": "enabled" if settings.redis_url else "in-memory",
            "audit_chain_ok": ok,
            "audit_entries": len(n),
            "audit_message": msg,
        }

    return app


app = create_app()
