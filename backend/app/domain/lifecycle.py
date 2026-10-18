"""
选举生命周期状态机 (Election lifecycle state machine)
=====================================================

对应课程 Lecture 5「Behavioral models / State machine models」：
用有限状态机描述系统如何响应事件。

    scheduled ──▶ open ──▶ closed ──▶ published

设计要点（写进报告）：
1. **所有**状态变更必须经过 assert_transition()，非法迁移直接抛异常；
2. 是否接受投票的判据是「当前状态是否为 open」，**不是**比较系统时间 ——
   时间只用于自动推进状态，状态才是唯一真相来源，这样可以避免
   "截止那一秒"的竞态导致漏票或超投。
"""

from __future__ import annotations

SCHEDULED = "scheduled"
OPEN = "open"
CLOSED = "closed"
PUBLISHED = "published"

ALL_STATES: tuple[str, ...] = (SCHEDULED, OPEN, CLOSED, PUBLISHED)

TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCHEDULED: (OPEN,),
    OPEN: (CLOSED,),
    CLOSED: (PUBLISHED,),
    PUBLISHED: (),
}

LABELS: dict[str, str] = {
    SCHEDULED: "未开始",
    OPEN: "投票进行中",
    CLOSED: "已截止",
    PUBLISHED: "结果已公布",
}


class InvalidTransition(Exception):
    """非法状态迁移。"""


class ElectionNotOpen(Exception):
    """选举当前不接受投票。"""


def can_transition(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, ())


def assert_transition(old: str, new: str) -> None:
    if old not in ALL_STATES:
        raise InvalidTransition(f"未知状态: {old!r}")
    if new not in ALL_STATES:
        raise InvalidTransition(f"未知状态: {new!r}")
    if not can_transition(old, new):
        allowed = TRANSITIONS[old] or ("（终态，不可再迁移）",)
        raise InvalidTransition(f"不允许从 {old} 迁移到 {new}；允许: {list(allowed)}")


def assert_accepts_ballots(state: str) -> None:
    if state != OPEN:
        raise ElectionNotOpen(f"选举状态为 {state}（{LABELS.get(state, state)}），不接受投票")
