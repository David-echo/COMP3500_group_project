"""
选举状态机 (Election lifecycle state machine)
=============================================

对应用户需求：选举必须严格按 未开始 -> 进行中 -> 已截止 -> 已公布 推进。
非法跳转必须被拒绝 —— 这是物流原型里真实存在的缺陷
（/api/dispatch 直接赋值 order['status']，绕过了状态机校验），
本系统把状态迁移集中在一个地方，任何写入路径都必须经过它。
"""

from __future__ import annotations


SCHEDULED = "scheduled"    # 未开始：可录入选民，不可投票
OPEN = "open"              # 进行中：可投票
CLOSED = "closed"          # 已截止：不可投票，可计票
PUBLISHED = "published"    # 已公布：结果公开，一切写入冻结

ALL_STATES = (SCHEDULED, OPEN, CLOSED, PUBLISHED)

# 允许的迁移
TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCHEDULED: (OPEN,),
    OPEN: (CLOSED,),
    CLOSED: (PUBLISHED,),
    PUBLISHED: (),
}


class InvalidTransition(Exception):
    """非法状态迁移。"""


class ElectionClosed(Exception):
    """选举不接受投票。"""


def can_transition(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, ())


def assert_transition(old: str, new: str) -> None:
    """任何状态变更的唯一入口。非法迁移直接抛异常。"""
    if old not in ALL_STATES:
        raise InvalidTransition(f"未知状态：{old!r}")
    if new not in ALL_STATES:
        raise InvalidTransition(f"未知状态：{new!r}")
    if not can_transition(old, new):
        allowed = TRANSITIONS[old] or ("（终态，不可再迁移）",)
        raise InvalidTransition(
            f"不允许从 {old} 迁移到 {new}；允许的目标状态为 {list(allowed)}"
        )


def assert_accepts_ballots(state: str) -> None:
    """
    投票写入前的守卫。

    关键点：判据是"当前状态是否为 OPEN"，而不是"当前时间是否在窗口内"。
    时间只用于自动推进状态，状态本身是唯一真相来源 ——
    这样截止那一刻的竞态就不会漏票。见 db.tick_elections()。
    """
    if state != OPEN:
        raise ElectionClosed(
            f"选举当前状态为 {state}，不接受投票（仅 {OPEN} 可投票）"
        )
