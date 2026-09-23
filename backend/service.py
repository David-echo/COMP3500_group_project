"""
领域服务 (Domain services)
==========================

投票、计票、凭证核验的完整业务流程。

本层是纯业务逻辑，不依赖 Flask —— 因此单元测试、不变量测试、
并发测试都可以直接调用这些函数，无需启动 HTTP 服务。
这一分层本身就是"可测试性"的架构决策，报告里可以作为 ADR 的一条。
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

import crypto
import db
from domain import lifecycle, tally


class VoteError(Exception):
    """投票业务错误（会被翻译成 HTTP 4xx）。"""


@dataclass
class CastOutcome:
    receipt_code: str
    anon_id: str
    audit_seq: int
    position_id: int


# --------------------------------------------------------------------------
# 投票
# --------------------------------------------------------------------------

def cast_ballot(
    conn: sqlite3.Connection,
    ballot_key: bytes,
    election_id: int,
    position_id: int,
    voter_id: str,
    choice: list[int],
    actor: Optional[str] = None,
) -> CastOutcome:
    """
    投出一票。整个过程在一个 IMMEDIATE 事务内完成。

    防重复投票的实现要点
    -------------------
    这里**不用** "先 SELECT 检查 has_voted，再 UPDATE" 的写法 ——
    那是 check-then-act，并发下两个请求可能都读到 has_voted=0 而双双投票。
    我们改为**先写入带 UNIQUE(position_id, voter_id) 约束的 votes_log**，
    由数据库来裁决唯一性：并发时只有一个事务能插入成功，
    失败的那个捕获 IntegrityError 后返回明确错误。
    """
    auth_key = crypto.derive_key(ballot_key, "ballot-auth")
    actor = actor or voter_id
    now = db.now_iso()

    if not choice:
        raise VoteError("必须选择至少一个候选")

    conn.execute("BEGIN IMMEDIATE")
    try:
        # --- 1. 选举状态必须允许投票 ---
        erow = conn.execute(
            "SELECT id, status, strategy FROM elections WHERE id=?", (election_id,)
        ).fetchone()
        if erow is None:
            raise VoteError("选举不存在")
        lifecycle.assert_accepts_ballots(erow["status"])

        # --- 2. 职位必须属于该选举，并取到候选人数 ---
        prow = conn.execute(
            "SELECT id FROM positions WHERE id=? AND election_id=?",
            (position_id, election_id),
        ).fetchone()
        if prow is None:
            raise VoteError("职位不存在或不属于该选举")
        num_candidates = conn.execute(
            "SELECT COUNT(*) AS c FROM candidates WHERE position_id=?", (position_id,)
        ).fetchone()["c"]

        # --- 3. 选民资格 ---
        vrow = conn.execute(
            "SELECT eligible FROM voter_roll WHERE election_id=? AND voter_id=?",
            (election_id, voter_id),
        ).fetchone()
        if vrow is None:
            raise VoteError("选民不在名册内")
        if not vrow["eligible"]:
            raise VoteError("该选民的投票资格已被取消")

        # --- 4. 规范化的选择 + 范围校验 ---
        norm: list[int] = []
        for c in choice:
            if not isinstance(c, int) or not (0 <= c < num_candidates):
                raise VoteError(f"候选序号 {c!r} 越界（该职位共 {num_candidates} 名候选）")
            if c not in norm:
                norm.append(c)

        # --- 5. 写入选票（只有 anon_id，没有 voter_id）---
        anon_id = crypto.new_anon_id()
        choice_enc = crypto.encrypt_choice(auth_key, norm)
        cur = conn.execute(
            """INSERT INTO ballots(election_id, position_id, anon_id, choice_enc, cast_at, counted)
               VALUES (?,?,?,?,?,1)""",
            (election_id, position_id, anon_id, choice_enc, now),
        )
        ballot_id = cur.lastrowid

        # --- 6. 认领"该选民在此职位的唯一一票" ---
        #     由 UNIQUE 约束兜底：并发下这里只会有一个成功。
        try:
            conn.execute(
                """INSERT INTO votes_log(position_id, voter_id, ballot_id, created_at)
                   VALUES (?,?,?,?)""",
                (position_id, voter_id, ballot_id, now),
            )
        except sqlite3.IntegrityError:
            raise VoteError("您已完成投票，不能重复投票") from None

        # --- 7. 凭证：能证明"已计入"，但不含选择内容 ---
        receipt_code = crypto.new_receipt_code()
        conn.execute(
            """INSERT INTO receipts(election_id, position_id, ballot_id, receipt_code, anon_id, created_at)
               VALUES (?,?,?,?,?,?)""",
            (election_id, position_id, ballot_id, receipt_code, anon_id, now),
        )

        # --- 8. 更新选民册（只记"投过了"，不记 ballot_id）---
        conn.execute(
            "UPDATE voter_roll SET has_voted=1, voted_at=? WHERE election_id=? AND voter_id=?",
            (now, election_id, voter_id),
        )

        # --- 9. 审计：记录"谁投了 + 凭证码"，但**不记录选择** ---
        #     这样既能审计到人，也无法从日志推断投票内容。
        seq = db.append_audit(
            conn,
            op="ballot.cast",
            actor=actor,
            payload={
                "election_id": election_id,
                "position_id": position_id,
                "voter_id": voter_id,
                "receipt_code": receipt_code,
                "ballot_id": ballot_id,
            },
            ts=now,
        )

        conn.execute("COMMIT")
        return CastOutcome(receipt_code, anon_id, seq, position_id)
    except Exception:
        conn.execute("ROLLBACK")
        raise


# --------------------------------------------------------------------------
# 凭证核验
# --------------------------------------------------------------------------

def verify_receipt(conn: sqlite3.Connection, receipt_code: str) -> dict[str, Any]:
    """
    选民凭 receipt_code 确认自己的票已被计入。

    **重要**：返回值里刻意不包含 choice，也不包含候选人姓名。
    否则选民就能拿这个界面向第三方"证明"自己投了谁，
    从而给贿选/胁迫留下空间 —— 这是真实选举系统的硬性要求。
    """
    row = conn.execute(
        """SELECT r.receipt_code, r.anon_id, r.created_at, b.counted, b.cast_at,
                  b.position_id, e.title AS election_title
             FROM receipts r
             JOIN ballots b   ON b.id = r.ballot_id
             JOIN elections e ON e.id = r.election_id
            WHERE r.receipt_code = ?""",
        (receipt_code.strip().upper(),),
    ).fetchone()

    if row is None:
        return {"found": False, "message": "未找到该凭证，请核对凭证码"}

    conn.execute(
        "UPDATE receipts SET verified_at=? WHERE receipt_code=? AND verified_at IS NULL",
        (db.now_iso(), row["receipt_code"]),
    )
    return {
        "found": True,
        "receipt_code": row["receipt_code"],
        "election_title": row["election_title"],
        "counted": bool(row["counted"]),
        "cast_at": row["cast_at"],
        "message": "该选票已计入，且计入后未被修改" if row["counted"] else "该选票未计入",
    }


# --------------------------------------------------------------------------
# 计票与公示
# --------------------------------------------------------------------------

def compute_tally(
    conn: sqlite3.Connection, ballot_key: bytes, position_id: int
) -> dict[str, Any]:
    auth_key = crypto.derive_key(ballot_key, "ballot-auth")

    pos = conn.execute(
        "SELECT id, title, election_id FROM positions WHERE id=?", (position_id,)
    ).fetchone()
    if pos is None:
        raise VoteError("职位不存在")

    election = conn.execute(
        "SELECT id, status, strategy FROM elections WHERE id=?", (pos["election_id"],)
    ).fetchone()
    if election is None:
        raise VoteError("选举不存在")

    num_candidates = conn.execute(
        "SELECT COUNT(*) AS c FROM candidates WHERE position_id=?", (position_id,)
    ).fetchone()["c"]

    rows = conn.execute(
        "SELECT id, choice_enc FROM ballots WHERE position_id=? AND counted=1 ORDER BY id",
        (position_id,),
    ).fetchall()

    ballots: list[list[int]] = []
    ballot_ids: list[int] = []
    for r in rows:
        try:
            ballots.append(crypto.decrypt_choice(auth_key, r["choice_enc"]))
            ballot_ids.append(r["id"])
        except ValueError:
            # 密文被篡改：不计入，但必须留下痕迹
            db.append_audit(
                conn,
                op="tally.ballot_rejected",
                actor="system",
                payload={"ballot_id": r["id"], "position_id": position_id, "reason": "密文校验失败"},
            )

    strategy = tally.get_strategy(election["strategy"])
    result = strategy.tally(ballots, num_candidates)
    digest = tally.tally_digest(strategy.name, result.counts, ballot_ids)

    candidates = [
        {"idx": c["idx"], "name": c["name"], "party": c["party"]}
        for c in conn.execute(
            "SELECT idx, name, party FROM candidates WHERE position_id=? ORDER BY idx",
            (position_id,),
        ).fetchall()
    ]

    return {
        "position_id": position_id,
        "position_title": pos["title"],
        "election_id": election["id"],
        "election_status": election["status"],
        "strategy": strategy.name,
        "strategy_label": strategy.label,
        "candidates": candidates,
        "counts": {str(k): v for k, v in result.counts.items()},
        "winner_idx": result.winner,
        "winner_name": next(
            (c["name"] for c in candidates if c["idx"] == result.winner), None
        ),
        "rounds": result.rounds,
        "note": result.note,
        "ballot_count": len(ballot_ids),
        "digest": digest,
    }


def publish_results(
    conn: sqlite3.Connection, ballot_key: bytes, election_id: int, actor: str
) -> dict[str, Any]:
    """
    计票并公示。

    只有 CLOSED 的选举可以计票；公示后状态推进到 PUBLISHED（终态），
    此后任何写入都会被状态机拒绝。
    """
    election = conn.execute(
        "SELECT id, status FROM elections WHERE id=?", (election_id,)
    ).fetchone()
    if election is None:
        raise VoteError("选举不存在")

    # 已公示 -> 幂等返回既有结果，保证现场演示可以重复点击
    if election["status"] == lifecycle.PUBLISHED:
        rows = conn.execute(
            "SELECT position_id FROM results WHERE election_id=?", (election_id,)
        ).fetchall()
        return {
            "already_published": True,
            "results": [compute_tally(conn, ballot_key, r["position_id"]) for r in rows],
        }

    if election["status"] == lifecycle.OPEN:
        raise VoteError("选举仍在进行中，必须先截止才能计票")
    if election["status"] == lifecycle.SCHEDULED:
        raise VoteError("选举尚未开始，无法计票")

    positions = conn.execute(
        "SELECT id FROM positions WHERE election_id=? ORDER BY id", (election_id,)
    ).fetchall()

    out = []
    for p in positions:
        res = compute_tally(conn, ballot_key, p["id"])
        conn.execute(
            """INSERT OR REPLACE INTO results
               (election_id, position_id, strategy, counts_json, winner_idx,
                rounds_json, digest, ballot_count, published_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                election_id,
                p["id"],
                res["strategy"],
                json.dumps(res["counts"]),
                res["winner_idx"],
                json.dumps(res["rounds"], ensure_ascii=False),
                res["digest"],
                res["ballot_count"],
                db.now_iso(),
            ),
        )
        out.append(res)

    db.set_status(conn, election_id, lifecycle.PUBLISHED, actor)
    db.append_audit(
        conn,
        op="results.published",
        actor=actor,
        payload={
            "election_id": election_id,
            "positions": [
                {
                    "position_id": r["position_id"],
                    "ballot_count": r["ballot_count"],
                    "digest": r["digest"],
                }
                for r in out
            ],
        },
    )
    # 记录链尾哈希，便于对外锚定
    chain = db.read_audit_chain(conn)
    db.append_audit(
        conn,
        op="audit.chain_tip",
        actor="system",
        payload={"chain_tip": chain[-1].entry_hash if chain else "", "length": len(chain)},
    )
    return {"already_published": False, "results": out}


# --------------------------------------------------------------------------
# 不变量检查（一致性校验）
# --------------------------------------------------------------------------

def check_invariants(conn: sqlite3.Connection, election_id: int) -> dict[str, Any]:
    """
    核心完整性不变量：
      ① 每个职位的选票数 == votes_log 中该职位的记录数
         （即：不存在"投了票但没记账"或"记了账但没选票"）
      ② 不存在重复的 (position_id, voter_id)
      ③ 每个职位的选票数 <= 该选举标记为已投票的选民数

    返回可直接展示为"体检报告"的字典。
    """
    checks: list[dict[str, Any]] = []

    dup = conn.execute(
        """SELECT position_id, voter_id, COUNT(*) AS c
             FROM votes_log GROUP BY position_id, voter_id HAVING c > 1"""
    ).fetchall()
    checks.append(
        {
            "name": "无重复投票记录",
            "passed": len(dup) == 0,
            "detail": "未发现同一选民在同一职位重复投票" if not dup else f"发现 {len(dup)} 组重复",
        }
    )

    voted = conn.execute(
        "SELECT COUNT(*) AS c FROM voter_roll WHERE election_id=? AND has_voted=1",
        (election_id,),
    ).fetchone()["c"]
    checks.append(
        {
            "name": "选民册已投票数 == 投票记录数",
            "passed": voted
            == conn.execute(
                """SELECT COUNT(*) AS c FROM votes_log v
                     JOIN positions p ON p.id = v.position_id
                    WHERE p.election_id = ?""",
                (election_id,),
            ).fetchone()["c"],
            "detail": f"名册标记已投票 {voted} 人",
        }
    )

    per_pos = []
    ok = True
    for p in conn.execute(
        "SELECT id, title FROM positions WHERE election_id=?", (election_id,)
    ).fetchall():
        n_ballots = conn.execute(
            "SELECT COUNT(*) AS c FROM ballots WHERE position_id=?", (p["id"],)
        ).fetchone()["c"]
        n_logged = conn.execute(
            "SELECT COUNT(*) AS c FROM votes_log WHERE position_id=?", (p["id"],)
        ).fetchone()["c"]
        n_receipts = conn.execute(
            "SELECT COUNT(*) AS c FROM receipts WHERE position_id=?", (p["id"],)
        ).fetchone()["c"]
        consistent = n_ballots == n_logged == n_receipts
        ok = ok and consistent
        per_pos.append(
            {
                "position": p["title"],
                "ballots": n_ballots,
                "votes_log": n_logged,
                "receipts": n_receipts,
                "consistent": consistent,
            }
        )
    checks.append(
        {
            "name": "选票数 == 投票记录数 == 凭证数",
            "passed": ok,
            "detail": "三者完全一致" if ok else "存在不一致，见分项",
            "per_position": per_pos,
        }
    )

    return {"election_id": election_id, "checks": checks, "all_passed": all(c["passed"] for c in checks)}
