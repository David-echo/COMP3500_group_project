"""审计接口 (Audit router) —— 成员 3 / 5 负责"""

from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import select

from ..deps import AuditorUser, SessionDep
from ..models import AuditLog
from ..schemas import AuditEntryOut, AuditVerifyOut
from ..services import audit

router = APIRouter(prefix="/audit", tags=["审计"])


@router.get("/verify", response_model=AuditVerifyOut)
async def verify_chain(session: SessionDep, _: AuditorUser) -> AuditVerifyOut:
    """校验哈希链完整性；返回第一条断裂记录的序号。"""
    ok, bad, msg, tip = await audit.verify(session)
    chain = await audit.read_chain(session)
    return AuditVerifyOut(
        ok=ok, length=len(chain), first_bad_seq=bad, message=msg, chain_tip=tip
    )


@router.get("/entries", response_model=list[AuditEntryOut])
async def list_entries(
    session: SessionDep, _: AuditorUser, limit: int = 50
) -> list[AuditEntryOut]:
    limit = max(1, min(limit, 500))
    rows = (
        await session.execute(
            select(AuditLog).order_by(AuditLog.seq.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        AuditEntryOut(
            seq=r.seq,
            op=r.op,
            actor=r.actor,
            payload=json.loads(r.payload),
            ts=r.ts,
            hash=r.entry_hash[:20] + "…",
        )
        for r in rows
    ]
