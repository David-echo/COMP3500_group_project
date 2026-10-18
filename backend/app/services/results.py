"""
计票与公示服务 (Results service)
===============================

对应 SRS FR-7（截止后才可计票）、FR-8（结果摘要）、DR-1（投票期间不公开票数）。

流程：
    closed ──▶ 计票 ──▶ 写入 results ──▶ 状态推进 published ──▶ 推送 SSE 结果
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import lifecycle, tally
from ..models import (
    Ballot,
    Candidate,
    Election,
    Position,
    Receipt,
    Result,
    VoterRoll,
    VotesLog,
)
from ..security import decrypt_choice
from . import audit, pubsub
from .voting import VoteError


async def compute_tally(session: AsyncSession, position_id: int) -> dict:
    """对某个职位计票（纯计算 + 读取，不修改状态）。"""
    position = (
        await session.execute(select(Position).where(Position.id == position_id))
    ).scalar_one_or_none()
    if position is None:
        raise VoteError("NOT_FOUND", "职位不存在")

    election = (
        await session.execute(select(Election).where(Election.id == position.election_id))
    ).scalar_one()
    if election.status not in (lifecycle.CLOSED, lifecycle.PUBLISHED):
        raise VoteError("ELECTION_NOT_CLOSED", "选举尚未截止，不能计票")

    candidates = (
        await session.execute(
            select(Candidate)
            .where(Candidate.position_id == position_id)
            .order_by(Candidate.idx)
        )
    ).scalars().all()

    ballots = (
        await session.execute(
            select(Ballot)
            .where(Ballot.position_id == position_id, Ballot.counted.is_(True))
            .order_by(Ballot.id)
        )
    ).scalars().all()

    choices: list[list[int]] = []
    ballot_ids: list[int] = []
    for b in ballots:
        try:
            choices.append(decrypt_choice(b.choice_enc))
            ballot_ids.append(b.id)
        except Exception:
            # 密文损坏：不计入，但留下审计痕迹
            await audit.append(
                session,
                op="tally.ballot_rejected",
                actor="system",
                payload={"ballot_id": b.id, "position_id": position_id, "reason": "密文校验失败"},
            )

    strategy = tally.get_strategy(election.tally_method)
    result = strategy.tally(choices, len(candidates))
    digest = tally.tally_digest(strategy.name, result.counts, ballot_ids)

    return {
        "position_id": position_id,
        "position_title": position.title,
        "tally_method": strategy.name,
        "tally_label": strategy.label,
        "ballot_count": len(ballot_ids),
        "counts": {str(k): v for k, v in result.counts.items()},
        "winner_idx": result.winner,
        "winner_name": next(
            (c.name for c in candidates if c.idx == result.winner), None
        ),
        "digest": digest,
        "note": result.note,
        "rounds": result.rounds,
    }


async def publish(session: AsyncSession, election_id: int, actor: str) -> dict:
    """计票并公示，状态推进到 published（终态）。"""
    election = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if election is None:
        raise VoteError("NOT_FOUND", "选举不存在")

    # 已公示：幂等返回
    if election.status == lifecycle.PUBLISHED:
        rows = (
            await session.execute(
                select(Result).where(Result.election_id == election_id)
            )
        ).scalars().all()
        return {
            "published": True,
            "already": True,
            "results": [json.loads(r.counts_json) | {"digest": r.digest} for r in rows],
            "full": [_result_dict(r) for r in rows],
        }

    if election.status == lifecycle.CLOSED:
        lifecycle.assert_transition(lifecycle.CLOSED, lifecycle.PUBLISHED)
    else:
        raise VoteError("ELECTION_NOT_CLOSED", "选举尚未截止，不能计票公示")

    positions = (
        await session.execute(select(Position).where(Position.election_id == election_id))
    ).scalars().all()

    computed = []
    for p in positions:
        res = await compute_tally(session, p.id)
        existing = (
            await session.execute(select(Result).where(Result.position_id == p.id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Result(
                    election_id=election_id,
                    position_id=p.id,
                    tally_method=res["tally_method"],
                    counts_json=json.dumps(res["counts"]),
                    winner_idx=res["winner_idx"],
                    rounds_json=json.dumps(res["rounds"], ensure_ascii=False),
                    digest=res["digest"],
                    ballot_count=res["ballot_count"],
                    published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
        computed.append(res)

    election.status = lifecycle.PUBLISHED

    await audit.append(
        session,
        op="results.published",
        actor=actor,
        payload={
            "election_id": election_id,
            "positions": [
                {"position_id": r["position_id"], "ballot_count": r["ballot_count"],
                 "digest": r["digest"]}
                for r in computed
            ],
        },
    )
    await session.commit()

    # 推送结果（此时已截止，公开票数合规）
    await pubsub.get_pubsub().publish(
        pubsub.CHANNEL_RESULTS,
        {
            "election_id": election_id,
            "status": lifecycle.PUBLISHED,
            "results": [
                {"position_id": r["position_id"], "counts": r["counts"],
                 "winner_idx": r["winner_idx"], "digest": r["digest"]}
                for r in computed
            ],
        },
    )

    return {"published": True, "already": False, "full": computed}


def _result_dict(r: Result) -> dict:
    return {
        "position_id": r.position_id,
        "tally_method": r.tally_method,
        "counts": json.loads(r.counts_json),
        "winner_idx": r.winner_idx,
        "digest": r.digest,
        "ballot_count": r.ballot_count,
        "rounds": json.loads(r.rounds_json),
    }


async def get_results(session: AsyncSession, election_id: int) -> dict:
    """查询结果：截止/公示后公开；投票期间不公开。"""
    election = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if election is None:
        raise VoteError("NOT_FOUND", "选举不存在")

    if election.status in (lifecycle.SCHEDULED, lifecycle.OPEN):
        return {
            "published": False,
            "election_id": election_id,
            "status": election.status,
            "message": "选举尚未截止，计票结果不予公开（防止影响投票行为）",
            "results": [],
        }

    rows = (
        await session.execute(select(Result).where(Result.election_id == election_id))
    ).scalars().all()
    by_pos = {r.position_id: r for r in rows}

    positions = (
        await session.execute(select(Position).where(Position.election_id == election_id))
    ).scalars().all()

    out = []
    for p in positions:
        r = by_pos.get(p.id)
        if r is None:
            continue
        out.append(
            {
                "position_id": p.id,
                "position_title": p.title,
                "tally_method": r.tally_method,
                "tally_label": tally.get_strategy(r.tally_method).label,
                "ballot_count": r.ballot_count,
                "counts": json.loads(r.counts_json),
                "winner_idx": r.winner_idx,
                "winner_name": next(
                    (
                        c.name
                        for c in (
                            await session.execute(
                                select(Candidate).where(Candidate.position_id == p.id)
                            )
                        ).scalars().all()
                        if c.idx == r.winner_idx
                    ),
                    None,
                ),
                "digest": r.digest,
                "note": "",
                "rounds": json.loads(r.rounds_json),
            }
        )

    return {
        "published": True,
        "election_id": election_id,
        "status": election.status,
        "message": "",
        "results": out,
    }


# ==========================================================================
# 完整性不变量（SRS NFR-3）
# ==========================================================================

async def check_integrity(session: AsyncSession, election_id: int) -> dict:
    checks = []

    # ① 无重复投票
    dup = (
        await session.execute(
            select(VotesLog.position_id, VotesLog.user_id, func.count().label("c"))
            .group_by(VotesLog.position_id, VotesLog.user_id)
            .having(func.count() > 1)
        )
    ).all()
    checks.append(
        {
            "name": "无重复投票记录",
            "passed": len(dup) == 0,
            "detail": "未发现同一选民在同一职位重复投票" if not dup else f"发现 {len(dup)} 组重复",
        }
    )

    # ② 名册已投票数 == 投票记录数
    voted = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election_id, VoterRoll.has_voted.is_(True)
            )
        )
    ).scalar_one()
    logged = (
        await session.execute(
            select(func.count())
            .select_from(VotesLog)
            .join(Position, Position.id == VotesLog.position_id)
            .where(Position.election_id == election_id)
        )
    ).scalar_one()
    checks.append(
        {
            "name": "名册已投票数 == 投票记录数",
            "passed": voted == logged,
            "detail": f"名册 {voted} 人 / 记录 {logged} 条",
        }
    )

    # ③ 选票数 == 投票记录数 == 凭证数
    positions = (
        await session.execute(select(Position).where(Position.election_id == election_id))
    ).scalars().all()
    detail = []
    ok = True
    for p in positions:
        nb = (
            await session.execute(
                select(func.count()).select_from(Ballot).where(Ballot.position_id == p.id)
            )
        ).scalar_one()
        nl = (
            await session.execute(
                select(func.count()).select_from(VotesLog).where(VotesLog.position_id == p.id)
            )
        ).scalar_one()
        nr = (
            await session.execute(
                select(func.count()).select_from(Receipt).where(Receipt.position_id == p.id)
            )
        ).scalar_one()
        consistent = nb == nl == nr
        ok = ok and consistent
        detail.append(f"{p.title}: 票 {nb} / 记录 {nl} / 凭证 {nr}")
    checks.append(
        {
            "name": "选票数 == 投票记录数 == 凭证数",
            "passed": ok,
            "detail": "；".join(detail) if detail else "无职位",
        }
    )

    return {
        "election_id": election_id,
        "all_passed": all(c["passed"] for c in checks),
        "checks": checks,
    }
