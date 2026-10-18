"""
哈希链审计日志 (Tamper-evident audit log)
=========================================

设计目标
--------
提供一个"事后篡改必被发现"的追加型日志。

每条记录的哈希覆盖 (prev_hash, seq, op, actor, payload, ts) 的全部内容。
因此改动任意一条记录，都会导致其后所有记录的 prev_hash 对不上，
verify_chain() 会精确定位到第一条断裂的位置。

保证边界（诚实声明，见报告）
--------------------------
能防：掌握数据库写权限、但不重算整条链的攻击者（例如偷偷改一条投票结果）。
不能防：能同时重算整条链的攻击者 —— 除非把链尾哈希对外公示 / 做外部锚定。
本文件不声称"不可攻破"，只声称"防篡改可检测"。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional


GENESIS = "0" * 64

# payload 中允许出现的字段白名单。
# 用途：结构性地阻止"选票选择"被写进日志，否则审计日志会变成
# 把选民关联到选择的旁路，匿名性保证会被日志泄漏掉。
FORBIDDEN_AUDIT_KEYS = {
    "choice",
    "choice_enc",
    "choice_index",
    "ballot_choice",
    "voted_for",
    "candidate",
    "candidate_id",
}


def canonical(payload: Any) -> str:
    """确定性序列化：同一 payload 永远得到同一字符串（键排序 + 无多余空白）。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_hash(
    seq: int,
    op: str,
    actor: str,
    payload: Any,
    ts: str,
    prev_hash: str,
) -> str:
    """计算一条审计记录的哈希。"""
    body = "\x1f".join(
        [
            prev_hash,
            str(seq),
            op,
            actor,
            canonical(payload),
            ts,
        ]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def assert_no_forbidden_keys(payload: Any) -> None:
    """
    防御性校验：拒绝把投票选择写进审计日志。

    这是一个"把设计约束编码进代码"的例子 —— 匿名性不靠开发者自觉，
    而靠一个会在写入时直接抛异常的守卫。
    """
    if not isinstance(payload, dict):
        return
    bad = FORBIDDEN_AUDIT_KEYS.intersection(payload.keys())
    if bad:
        raise ValueError(
            f"审计日志禁止包含投票选择相关字段 {sorted(bad)}；"
            "这会破坏选票匿名性（把选民关联到选择）。"
        )


@dataclass(frozen=True)
class ChainRecord:
    seq: int
    op: str
    actor: str
    payload: dict
    ts: str
    prev_hash: str
    entry_hash: str


def verify_chain(records: list[ChainRecord] | list[dict]) -> tuple[bool, Optional[int], str]:
    """
    校验哈希链完整性。

    返回 (ok, first_bad_seq, message)
      - ok=True  -> (True, None, "...")
      - ok=False -> (False, 断裂记录的 seq, 具体原因)

    逐条重算哈希，并检查 seq 连续、prev_hash 与上一条的 entry_hash 一致。
    """
    prev = GENESIS
    expected_seq = 1

    for raw in records:
        rec = raw if isinstance(raw, ChainRecord) else ChainRecord(**raw)

        if rec.seq != expected_seq:
            return (
                False,
                rec.seq,
                f"序号不连续：期望 seq={expected_seq}，实际 seq={rec.seq}（可能有记录被删除）",
            )

        if rec.prev_hash != prev:
            return (
                False,
                rec.seq,
                f"链断裂于 seq={rec.seq}：prev_hash 与上一条的 entry_hash 不一致",
            )

        recomputed = compute_hash(
            seq=rec.seq,
            op=rec.op,
            actor=rec.actor,
            payload=rec.payload,
            ts=rec.ts,
            prev_hash=rec.prev_hash,
        )
        if recomputed != rec.entry_hash:
            return (
                False,
                rec.seq,
                f"链断裂于 seq={rec.seq}：记录内容与存储的哈希不符（记录被篡改）",
            )

        prev = rec.entry_hash
        expected_seq += 1

    return True, None, f"审计链完整：共 {len(records)} 条记录，链尾哈希 {prev[:16]}…"


def chain_tip(records: list[ChainRecord] | list[dict]) -> str:
    """返回链尾哈希（可用于对外公示 / 外部锚定）。"""
    if not records:
        return GENESIS
    last = records[-1]
    return last.entry_hash if isinstance(last, ChainRecord) else last["entry_hash"]
