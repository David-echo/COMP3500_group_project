"""
数据模型 (ORM Models)
====================

本文件承载本项目最重要的两个架构决策（见 docs/templates/ADR-template.md）：

【决策 1】选票与选民册**物理隔离** —— 保证匿名性
--------------------------------------------------
    voter_roll  : 记录「谁投了」   → 有 user_id，**没有 ballot_id**
    ballots     : 记录「投了什么」  → 有 anon_id，**没有 user_id**
    votes_log   : 一人一票仲裁     → 有 user_id，**没有 ballot_id / receipt_code / anon_id**
    receipts    : 凭证             → 有 ballot_id，**没有 user_id**（凭证码只发给选民本人）
    audit_log   : 审计             → ballot.cast 记录只含 user_id，**不含任何选票标识**

任何一张表都不同时持有「选民身份」与「选票标识」，
因此系统在任何时刻都不存在可关联「某选民」与「其选择」的字段或外键。
这不是"我们承诺不查日志"，而是数据模型里根本没有这条边。

【决策 2】一人一票由**数据库唯一约束**保证 —— 保证正确性
--------------------------------------------------
    votes_log.UNIQUE(position_id, user_id)

并发下也只有一个事务能插入成功，无需应用层 check-then-act。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


# ==========================================================================
# 账号
# ==========================================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="VOTER")  # VOTER / ADMIN / AUDITOR
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ==========================================================================
# 选举结构
# ==========================================================================

class Election(Base):
    __tablename__ = "elections"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # scheduled / open / closed / published（由 domain.lifecycle 控制）
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # fptp / irv（策略模式，见 domain.tally）
    tally_method: Mapped[str] = mapped_column(String(16), default="fptp")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    positions: Mapped[list["Position"]] = relationship(
        back_populates="election", cascade="all, delete-orphan", lazy="selectin"
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    seats: Mapped[int] = mapped_column(Integer, default=1)

    election: Mapped[Election] = relationship(back_populates="positions")
    candidates: Mapped[list["Candidate"]] = relationship(
        back_populates="position", cascade="all, delete-orphan", lazy="selectin"
    )


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("position_id", "idx", name="uq_candidate_idx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)          # 职位内序号，计票用
    name: Mapped[str] = mapped_column(String(120))
    party: Mapped[str] = mapped_column(String(120), default="")

    position: Mapped[Position] = relationship(back_populates="candidates")


# ==========================================================================
# 选民册（谁投了）—— 不含 ballot_id
# ==========================================================================

class VoterRoll(Base):
    __tablename__ = "voter_roll"
    __table_args__ = (UniqueConstraint("election_id", "user_id", name="uq_voter_roll"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    has_voted: Mapped[bool] = mapped_column(Boolean, default=False)
    voted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ==========================================================================
# 选票（投了什么）—— 不含 user_id
# ==========================================================================

class Ballot(Base):
    __tablename__ = "ballots"

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id", ondelete="CASCADE"), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    # 与选民无关的随机标识（不是 user_id）
    anon_id: Mapped[str] = mapped_column(String(64), index=True)
    # AES-GCM 加密后的选择，例如 "0,2,1"
    choice_enc: Mapped[str] = mapped_column(Text)
    cast_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    counted: Mapped[bool] = mapped_column(Boolean, default=True)


class Receipt(Base):
    """凭证：让选民确认「票被计入」，但**不含选择内容**。"""

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id", ondelete="CASCADE"), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    ballot_id: Mapped[int] = mapped_column(ForeignKey("ballots.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    anon_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VotesLog(Base):
    """
    投票记录：唯一约束在此仲裁"一人一票"。
    只记录「某人在某职位投过」，不记录选择（选择在 ballots）。
    **同样不含 ballot_id / receipt_code / anon_id**：
    否则本表会成为「选民 → 选票」的关联边，破坏匿名性（见 ADR-001）。
    """

    __tablename__ = "votes_log"
    __table_args__ = (UniqueConstraint("position_id", "user_id", name="uq_one_vote_per_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ==========================================================================
# 结果与审计
# ==========================================================================

class Result(Base):
    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("position_id", name="uq_result_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id", ondelete="CASCADE"), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"))
    tally_method: Mapped[str] = mapped_column(String(16))
    counts_json: Mapped[str] = mapped_column(Text)        # {"0": 12, "1": 20}
    winner_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rounds_json: Mapped[str] = mapped_column(Text, default="[]")
    digest: Mapped[str] = mapped_column(String(64))
    ballot_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """追加型哈希链审计日志：每条记录的哈希包含上一条的哈希。"""

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)          # JSON 字符串
    ts: Mapped[str] = mapped_column(String(32))
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


# ==========================================================================
# 索引
# ==========================================================================

Index("ix_ballot_position", Ballot.position_id)
Index("ix_votes_election", VotesLog.position_id, VotesLog.user_id)
