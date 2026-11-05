"""
投票服务 (Voting service)
=========================

业务核心。对应 ADR-002 / ADR-003：

1. **一人一票**由数据库唯一约束 votes_log(position_id, user_id) 仲裁，
   **不使用** "先 SELECT 检查再 INSERT" 的 check-then-act 写法（并发下会双投）。
2. **物理隔离**：ballots 不含 user_id；voter_roll / votes_log 不含 ballot_id；
   审计日志的 ballot.cast 记录不含任何选票标识（ballot_id / receipt_code / anon_id）。
   任何一张表都不同时持有「选民身份」与「选票标识」。
3. 整个投票在一个事务内完成，任一步失败全部回滚。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import lifecycle
from ..models import (
    Ballot,
    Candidate,
    Election,
    Position,
    Receipt,
    VoterRoll,
    VotesLog,
)
from ..security import encrypt_choice, new_anon_id, new_receipt_code
from . import audit, pubsub


class VoteError(Exception):
    """业务错误，路由层翻译为 4xx。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CastResult:
    def __init__(self, receipt_code: str, cast_at: datetime, audit_seq: int) -> None:
        self.receipt_code = receipt_code
        self.cast_at = cast_at
        self.audit_seq = audit_seq


async def cast_ballot(
    session: AsyncSession,
    *,
    election_id: int,
    position_id: int,
    user_id: int,
    actor: str,
    choice: list[int],
) -> CastResult:
    # --- 参数基本校验 ---
    if not choice:
        raise VoteError("INVALID_CHOICE", "必须选择至少一个候选")

    # --- 选举状态 ---
    election = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if election is None:
        raise VoteError("NOT_FOUND", "选举不存在")
    lifecycle.assert_accepts_ballots(election.status)

    # --- 职位与候选人数 ---
    position = (
        await session.execute(
            select(Position).where(
                Position.id == position_id, Position.election_id == election_id
            )
        )
    ).scalar_one_or_none()
    if position is None:
        raise VoteError("NOT_FOUND", "职位不存在或不属于该选举")

    num_candidates = (
        await session.execute(
            select(func.count()).select_from(Candidate).where(
                Candidate.position_id == position_id
            )
        )
    ).scalar_one()

    # --- 名册与资格 ---
    roll = (
        await session.execute(
            select(VoterRoll).where(
                VoterRoll.election_id == election_id, VoterRoll.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if roll is None:
        raise VoteError("FORBIDDEN", "您不在该选举的选民名册内")
    if not roll.eligible:
        raise VoteError("FORBIDDEN", "您的投票资格已被取消")

    # --- 规范化选择 ---
    norm: list[int] = []
    for c in choice:
        if not isinstance(c, int) or not (0 <= c < num_candidates):
            raise VoteError("INVALID_CHOICE", f"候选序号 {c} 越界（共 {num_candidates} 名候选）")
        if c not in norm:
            norm.append(c)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    anon_id = new_anon_id()

    try:
        # --- 1) 写选票（无 user_id）---
        ballot = Ballot(
            election_id=election_id,
            position_id=position_id,
            anon_id=anon_id,
            choice_enc=encrypt_choice(norm),
            cast_at=now,
            counted=True,
        )
        session.add(ballot)
        await session.flush()  # 取得 ballot.id

        # --- 2) 由唯一约束仲裁"一人一票"（不含 ballot_id，避免形成选民→选票的关联边）---
        session.add(
            VotesLog(
                position_id=position_id,
                user_id=user_id,
                created_at=now,
            )
        )
        await session.flush()  # 冲突在此抛出 IntegrityError

    except IntegrityError as exc:
        await session.rollback()
        raise VoteError("DUPLICATE_VOTE", "您已完成投票，不能重复投票") from exc

    # --- 3) 凭证 ---
    receipt = Receipt(
        election_id=election_id,
        position_id=position_id,
        ballot_id=ballot.id,
        code=new_receipt_code(),
        anon_id=anon_id,
        created_at=now,
    )
    session.add(receipt)

    # --- 4) 更新名册（只记"投过了"）---
    roll.has_voted = True
    roll.voted_at = now

    # --- 5) 审计 ---
    # 匿名性守卫：payload 只允许含「谁投了」（user_id），
    # 不得携带 ballot_id / receipt_code / anon_id —— 否则哈希链日志
    # 会变成一张永久的「选民 ↔ 选票」对照表，且因不可篡改而无法撤销。
    seq = await audit.append(
        session,
        op="ballot.cast",
        actor=actor,
        payload={
            "election_id": election_id,
            "position_id": position_id,
            "user_id": user_id,
        },
        ts=now.isoformat(),
    )

    await session.commit()

    # --- 6) 推送投票率（不含任何候选人票数）---
    await _publish_turnout(session, election_id)

    return CastResult(receipt.code, now, seq)


async def _publish_turnout(session: AsyncSession, election_id: int) -> None:
    """投票期间只公开投票率，不公开各候选人票数（SRS DR-1）。"""
    total = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election_id
            )
        )
    ).scalar_one()
    voted = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election_id, VoterRoll.has_voted.is_(True)
            )
        )
    ).scalar_one()
    await pubsub.get_pubsub().publish(
        pubsub.CHANNEL_TURNOUT,
        {
            "election_id": election_id,
            "voted": voted,
            "total": total,
            "percent": round(voted * 100.0 / total, 1) if total else 0.0,
        },
    )


async def verify_receipt(session: AsyncSession, code: str) -> dict:
    """
    凭证核验。**刻意不返回 choice / candidate**：
    否则选民可拿它向第三方"证明"投票选择，为贿选与胁迫留门。
    """
    code = code.strip().upper()
    row = (
        await session.execute(
            select(Receipt, Ballot, Election)
            .join(Ballot, Ballot.id == Receipt.ballot_id)
            .join(Election, Election.id == Receipt.election_id)
            .where(Receipt.code == code)
        )
    ).first()

    if row is None:
        return {"found": False, "message": "未找到该凭证，请核对凭证码"}

    receipt, ballot, election = row
    if receipt.verified_at is None:
        receipt.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()

    return {
        "found": True,
        "message": "该选票已计入，且计入后未被修改" if ballot.counted else "该选票未计入",
        "election_title": election.title,
        "counted": bool(ballot.counted),
        "cast_at": ballot.cast_at,
    }
