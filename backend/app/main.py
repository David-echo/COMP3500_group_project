"""Module."""
from __future__ import annotations
import contextlib
from typing import AsyncIterator
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import config as config_module
from .api import audit, auth, elections, events, results, votes
from .db import Base, engine
from .services import pubsub
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
            "COMP 3500SEF group project - Election Management and Voting System\n\n"
            "Backend: Python, FastAPI, SQLAlchemy 2.0\n"
            "Data: PostgreSQL, falling back to SQLite in development\n"
            "Real-time: SSE"
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
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        parts: list[str] = []
        for err in exc.errors():
            loc = [str(x) for x in err.get("loc", []) if x not in ("body", "query", "path")]
            field = ".".join(loc) if loc else "request"
            parts.append(f"{field}: {err.get('msg', 'invalid format')}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "；".join(parts) or "Request validation failed"},
        )
    for r in (auth.router, elections.router, votes.router, results.router,
              audit.router, events.router):
        app.include_router(r, prefix=settings.api_prefix)
    @app.get("/api/health", tags=["System"])
    async def health() -> dict:
        """Health."""
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
