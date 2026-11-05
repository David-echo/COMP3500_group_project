"""
哈希链审计日志 (Tamper-evident audit log)
=========================================

每条记录的哈希覆盖 (prev_hash, seq, op, actor, payload, ts)。
改动任意一条，其后所有记录的 prev_hash 都对不上，verify() 能精确定位断裂点。

保证边界（诚实声明，写进报告）
----------------------------
能防：掌握数据库写权限但不重算整条链的攻击者（例如偷改一条投票结果）。
不能防：能同时重算整条链的攻击者 —— 除非把链尾哈希对外公示做外部锚定。
本模块**不声称**"不可攻破"，只声称"防篡改可检测"。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

GENESIS = "0" * 64

# 禁止写入审计日志的字段：否则日志会变成"把选民关联到选择"的旁路。
FORBIDDEN_KEYS = {
    "choice",
    "choice_enc",
    "candidate",
    "candidate_id",
    "voted_for",
    "ballot_choice",
}

# 选票标识字段：允许单独出现（如 tally.ballot_rejected，本身是匿名的），
# 但**不得**与选民身份字段（user_id / student_id）出现在同一条 payload 中，
# 否则该条记录即成为「选民 ↔ 选票」的关联边。
BALLOT_LINK_KEYS = {"ballot_id", "anon_id", "receipt_code"}
IDENTITY_KEYS = {"user_id", "student_id"}


def canonical(payload: Any) -> str:
    """确定性序列化：与字典键顺序无关。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_hash(seq: int, op: str, actor: str, payload: Any, ts: str, prev_hash: str) -> str:
    body = "\x1f".join([prev_hash, str(seq), op, actor, canonical(payload), ts])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def assert_no_forbidden_keys(payload: Any) -> None:
    """守卫：拒绝把投票选择写入日志。"""
    if not isinstance(payload, dict):
        return
    bad = FORBIDDEN_KEYS.intersection(payload.keys())
    if bad:
        raise ValueError(
            f"审计日志禁止包含投票选择字段 {sorted(bad)}：这会破坏选票匿名性"
        )
    # 组合守卫：选民身份 + 选票标识不得同条出现（嵌套 payload 递归检查）
    if _has_identity(payload) and _has_ballot_link(payload):
        raise ValueError(
            "审计日志禁止在同一条记录中同时包含选民身份字段与选票标识字段"
            f"（{sorted(IDENTITY_KEYS)} × {sorted(BALLOT_LINK_KEYS)}）："
            "这会形成「选民 ↔ 选票」的永久关联边，破坏匿名性"
        )


def _iter_flat_keys(payload: Any):
    """深度优先遍历嵌套 dict / list 中的所有键名。"""
    if isinstance(payload, dict):
        for k, v in payload.items():
            yield str(k)
            yield from _iter_flat_keys(v)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_flat_keys(item)


def _has_identity(payload: Any) -> bool:
    return any(k in IDENTITY_KEYS for k in _iter_flat_keys(payload))


def _has_ballot_link(payload: Any) -> bool:
    return any(k in BALLOT_LINK_KEYS for k in _iter_flat_keys(payload))


@dataclass(frozen=True)
class ChainRecord:
    seq: int
    op: str
    actor: str
    payload: dict
    ts: str
    prev_hash: str
    entry_hash: str


def verify_chain(records: list[ChainRecord]) -> tuple[bool, Optional[int], str]:
    """返回 (ok, first_bad_seq, message)。"""
    prev = GENESIS
    expected = 1
    for r in records:
        if r.seq != expected:
            return False, r.seq, f"序号不连续：期望 {expected}，实际 {r.seq}（可能有记录被删除）"
        if r.prev_hash != prev:
            return False, r.seq, f"链断裂于 seq={r.seq}：prev_hash 与上一条哈希不一致"
        if compute_hash(r.seq, r.op, r.actor, r.payload, r.ts, r.prev_hash) != r.entry_hash:
            return False, r.seq, f"链断裂于 seq={r.seq}：记录内容与存储哈希不符（被篡改）"
        prev = r.entry_hash
        expected += 1
    return True, None, f"审计链完整：共 {len(records)} 条记录，链尾 {prev[:16]}…"


def chain_tip(records: list[ChainRecord]) -> str:
    return records[-1].entry_hash if records else GENESIS
