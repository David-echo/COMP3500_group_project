"""
审计服务 (Audit service)
========================

所有"值得记账"的操作都通过 append() 写入哈希链。
payload 会先经过 forbid 校验，防止把投票选择写进日志（匿名性守卫）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import hashchain
from ..models import AuditLog


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def append(
    session: AsyncSession,
    op: str,
    actor: str,
    payload: dict,
    ts: str | None = None,
) -> int:
    """追加一条审计记录，返回其 seq。"""
    hashchain.assert_no_forbidden_keys(payload)
    ts = ts or now_iso()

    last = (
        await session.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
    ).scalar_one_or_none()
    prev = last.entry_hash if last else hashchain.GENESIS
    seq = (last.seq + 1) if last else 1

    entry_hash = hashchain.compute_hash(
        seq=seq, op=op, actor=actor, payload=payload, ts=ts, prev_hash=prev
    )
    session.add(
        AuditLog(
            seq=seq,
            op=op,
            actor=actor,
            payload=hashchain.canonical(payload),
            ts=ts,
            prev_hash=prev,
            entry_hash=entry_hash,
        )
    )
    await session.flush()
    return seq


async def read_chain(session: AsyncSession) -> list[hashchain.ChainRecord]:
    rows = (
        await session.execute(select(AuditLog).order_by(AuditLog.seq.asc()))
    ).scalars().all()
    return [
        hashchain.ChainRecord(
            seq=r.seq,
            op=r.op,
            actor=r.actor,
            payload=json.loads(r.payload),
            ts=r.ts,
            prev_hash=r.prev_hash,
            entry_hash=r.entry_hash,
        )
        for r in rows
    ]


async def verify(session: AsyncSession) -> tuple[bool, int | None, str, str]:
    """返回 (ok, first_bad_seq, message, chain_tip)。"""
    chain = await read_chain(session)
    ok, bad, msg = hashchain.verify_chain(chain)
    return ok, bad, msg, hashchain.chain_tip(chain)
