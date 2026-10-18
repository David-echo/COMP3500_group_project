"""
计票策略 (Tally strategies)
===========================

对应课程 Lecture 6「Architectural patterns」中的可替换组件思想，
以及 Lecture 7/9 关注的「演化」：新增一种计票法只需新增一个类并注册，
**投票、存储、公示的代码不需要改动**。

v1 实现：
  - fptp  单选制（First Past The Post）
  - irv   排序复选制（Instant Runoff Voting）

计票是**纯函数**：输入选票列表，输出结果，不碰数据库 —— 因此可被完整单元测试。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, Sequence


@dataclass
class TallyResult:
    method: str
    counts: dict[int, int]
    winner: int | None
    rounds: list[dict] = field(default_factory=list)
    note: str = ""


class TallyStrategy(Protocol):
    name: str
    label: str

    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult: ...


class FPTPStrategy:
    name = "fptp"
    label = "单选制 (First Past The Post)"

    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult:
        counts = Counter()
        for b in ballots:
            if b and 0 <= b[0] < num_candidates:
                counts[b[0]] += 1
        full = {i: counts.get(i, 0) for i in range(num_candidates)}
        top = max(full.values()) if full else 0
        leaders = [i for i, v in full.items() if v == top]
        winner = leaders[0] if len(leaders) == 1 else None
        note = "" if len(leaders) <= 1 else f"并列最高票：候选 {leaders}"
        return TallyResult(self.name, full, winner, note=note)


class IRVStrategy:
    name = "irv"
    label = "排序复选制 (Instant Runoff)"

    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult:
        cleaned: list[list[int]] = []
        for b in ballots:
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
                {"remaining": list(remaining), "counts": full,
                 "exhausted": exhausted, "total": total}
            )

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

            fewest = min(full.values())
            losers = [c for c, v in full.items() if v == fewest]
            remaining.remove(max(losers))  # 并列时确定性淘汰序号较大者

        counts = Counter()
        for b in cleaned:
            for pref in b:
                if pref in remaining:
                    counts[pref] += 1
                    break
        full = {i: counts.get(i, 0) for i in remaining}
        ordered = sorted(full.items(), key=lambda kv: (-kv[1], kv[0]))
        winner = (
            ordered[0][0]
            if ordered and (len(ordered) == 1 or ordered[0][1] > ordered[1][1])
            else None
        )
        return TallyResult(
            self.name,
            {i: counts.get(i, 0) for i in range(num_candidates)},
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
        raise ValueError(f"未知计票方法: {name!r}；可用: {sorted(STRATEGIES)}")
    return STRATEGIES[name]


def tally_digest(method: str, counts: dict[int, int], ballot_ids: Sequence[int]) -> str:
    """
    结果摘要：绑定「计票方法 + 各候选票数 + 参与计票的选票 ID 集合」。
    第三方可用同一批选票复算并比对摘要，从而发现事后篡改。
    摘要不含任何选民身份信息。
    """
    body = "|".join(
        [
            method,
            ",".join(f"{k}:{v}" for k, v in sorted(counts.items())),
            ",".join(str(b) for b in sorted(ballot_ids)),
        ]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
