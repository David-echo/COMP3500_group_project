"""
计票策略 (Tallying strategies)
=============================

对应设计模式：**策略模式 (Strategy)**，也是课程 Topic 9「软件演化」的载体。

v1 只实现单选制 (FPTP)。排序复选制 (IRV) 作为演化阶段加入 ——
新增一种计票法只需新增一个类并注册，**不需要改动投票、存储或公示的任何代码**。
报告里可以直接论证："为什么当初的架构让这次演化只改了 1 个文件"。

计票是纯函数：输入 (选票列表, 候选人数)，输出结果。不碰数据库 ——
因此可以被单元测试和属性测试完整覆盖。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, Sequence


@dataclass
class TallyResult:
    method: str
    counts: dict[int, int]                 # 候选序号 -> 票数
    winner: int | None
    rounds: list[dict] = field(default_factory=list)   # IRV 的逐轮记录
    note: str = ""

    def total_votes(self) -> int:
        if self.method == "fptp":
            return sum(self.counts.values())
        # IRV: 每张有效选票在每一轮都算一票，总票数 = 第一轮
        return self.rounds[0]["total"] if self.rounds else 0


class TallyStrategy(Protocol):
    name: str

    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult:
        ...


class FPTPStrategy:
    """单选制：每人一票，得票最多者当选（并列则 winner=None）。"""

    name = "fptp"
    label = "单选制 (First Past The Post)"

    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult:
        counts = Counter()
        for b in ballots:
            if not b:
                continue
            first = b[0]
            if 0 <= first < num_candidates:
                counts[first] += 1

        full = {i: counts.get(i, 0) for i in range(num_candidates)}
        top = max(full.values()) if full else 0
        leaders = [i for i, v in full.items() if v == top]

        winner = leaders[0] if len(leaders) == 1 else None
        note = "" if len(leaders) <= 1 else f"并列最高票：候选 {leaders}，需重新投票或按章程处理"
        return TallyResult(self.name, full, winner, note=note)


class IRVStrategy:
    """
    排序复选制 (Instant Runoff Voting)。
    每轮淘汰得票最少者，把被淘汰者作为第一选择的选票按下一顺位转移，
    直到有人获得 > 50% 或只剩两人。

    —— 这是"演化"阶段加入的功能，用于演示架构的可扩展性。
    """

    name = "irv"
    label = "排序复选制 (Instant Runoff)"

    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult:
        valid = [list(b) for b in ballots if b]
        # 清洗：去重、去越界
        cleaned: list[list[int]] = []
        for b in valid:
            seen, c = set(), []
            for x in b:
                if isinstance(x, int) and 0 <= x < num_candidates and x not in seen:
                    seen.add(x)
                    c.append(x)
            if c:
                cleaned.append(c)

        remaining = list(range(num_candidates))
        rounds: list[dict] = []
        total = len(cleaned)

        while len(remaining) > 1:
            counts = Counter()
            exhausted = 0
            for b in cleaned:
                for pref in b:
                    if pref in remaining:
                        counts[pref] += 1
                        break
                else:
                    exhausted += 1

            full = {i: counts.get(i, 0) for i in remaining}
            rounds.append(
                {
                    "remaining": list(remaining),
                    "counts": full,
                    "exhausted": exhausted,
                    "total": total,
                }
            )

            # 有人过半 -> 直接胜出
            for cand, votes in full.items():
                if votes * 2 > total:
                    return TallyResult(
                        self.name,
                        {i: counts.get(i, 0) for i in range(num_candidates)},
                        cand,
                        rounds=rounds,
                        note=f"第 {len(rounds)} 轮过半数胜出",
                    )

            if len(remaining) == 2:
                break

            # 淘汰得票最少者（并列时淘汰序号较大者，保证确定性）
            fewest = min(full.values())
            losers = [c for c, v in full.items() if v == fewest]
            remaining.remove(max(losers))

        # 只剩两人且无人过半 -> 比较两人票数
        counts = Counter()
        for b in cleaned:
            for pref in b:
                if pref in remaining:
                    counts[pref] += 1
                    break
        full = {i: counts.get(i, 0) for i in remaining}
        ordered = sorted(full.items(), key=lambda kv: (-kv[1], kv[0]))
        winner = ordered[0][0] if ordered and (len(ordered) == 1 or ordered[0][1] > ordered[1][1]) else None
        final_counts = {i: counts.get(i, 0) for i in range(num_candidates)}
        return TallyResult(
            self.name,
            final_counts,
            winner,
            rounds=rounds,
            note="最后一轮比较最高两名" if winner is not None else "最终仍并列",
        )


STRATEGIES: dict[str, TallyStrategy] = {
    FPTPStrategy.name: FPTPStrategy(),
    IRVStrategy.name: IRVStrategy(),
}


def get_strategy(name: str) -> TallyStrategy:
    if name not in STRATEGIES:
        raise ValueError(f"未知计票方法：{name!r}；可用：{sorted(STRATEGIES)}")
    return STRATEGIES[name]


def tally_digest(strategy_name: str, counts: dict[int, int], ballot_ids: Sequence[int]) -> str:
    """
    结果摘要：绑定"计票方法 + 各项票数 + 参与计票的选票ID集合"。
    第三方可用同一批选票复算并比对摘要，从而发现事后篡改计票结果。
    摘要本身不含任何选民身份信息。
    """
    import hashlib

    body = "|".join(
        [
            strategy_name,
            ",".join(f"{k}:{v}" for k, v in sorted(counts.items())),
            ",".join(str(b) for b in sorted(ballot_ids)),
        ]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
