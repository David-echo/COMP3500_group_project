"""Module."""
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
    label = "First Past The Post"
    def tally(self, ballots: Sequence[Sequence[int]], num_candidates: int) -> TallyResult:
        counts = Counter()
        for b in ballots:
            if b and 0 <= b[0] < num_candidates:
                counts[b[0]] += 1
        full = {i: counts.get(i, 0) for i in range(num_candidates)}
        top = max(full.values()) if full else 0
        leaders = [i for i, v in full.items() if v == top]
        winner = leaders[0] if len(leaders) == 1 else None
        note = "" if len(leaders) <= 1 else f"Tie for most votes: candidates {leaders}"
        return TallyResult(self.name, full, winner, note=note)
class IRVStrategy:
    name = "irv"
    label = "Instant Runoff (Ranked Choice)"
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
                        note=f"Majority reached in round {len(rounds)}",
                    )
            if len(remaining) == 2:
                break
            fewest = min(full.values())
            losers = [c for c, v in full.items() if v == fewest]
            remaining.remove(max(losers))
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
            note="Final round compares the top two" if winner is not None else "Still tied after the final round",
        )
STRATEGIES: dict[str, TallyStrategy] = {
    FPTPStrategy.name: FPTPStrategy(),
    IRVStrategy.name: IRVStrategy(),
}
def get_strategy(name: str) -> TallyStrategy:
    if name not in STRATEGIES:
        raise ValueError(f"Unknown tally method: {name!r}; available: {sorted(STRATEGIES)}")
    return STRATEGIES[name]
def tally_digest(method: str, counts: dict[int, int], ballot_ids: Sequence[int]) -> str:
    """Tally digest."""
    body = "|".join(
        [
            method,
            ",".join(f"{k}:{v}" for k, v in sorted(counts.items())),
            ",".join(str(b) for b in sorted(ballot_ids)),
        ]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
