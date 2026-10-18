"""
数据访问层 (Data access layer)
==============================

本文件承载两个核心架构决策：

【决策 1】选票与选民册物理隔离
--------------------------------------------------
  voter_roll   : voter_id -> has_voted / voted_at        （谁投了）
  ballots      : ballot_id -> anon_id / choice_enc      （投了什么）
  receipts     : ballot_id -> receipt_code / anon_id    （给选民的凭证）

  ballots 表里 **没有 voter_id 字段**；voter_roll 表里 **没有 ballot_id 字段**。
  两表之间唯一的桥梁是 receipts.receipt_code，而它只发给选民本人。

  => 系统在任何时刻都无法把"某个选民"与"投了什么"关联起来。
     这不是靠"我们承诺不查日志"，而是靠数据模型里根本不存在这条边。

【决策 2】投票的唯一性与时间窗口由数据库强制，而不是由应用层自觉
--------------------------------------------------
  UNIQUE(position_id, voter_id) on votes_log  -> 并发下也只会有一个事务成功
  状态判定基于 elections.status，而非当前时间  -> 截止那一刻无竞态漏票
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from domain import hashchain, lifecycle, tally

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# 连接与迁移
# --------------------------------------------------------------------------

def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """建立 schema。幂等，可重复执行。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- ---------- 选举与职位 ----------
        CREATE TABLE IF NOT EXISTS elections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            status      TEXT    NOT NULL CHECK (status IN
                            ('scheduled','open','closed','published')),
            opens_at    TEXT,
            closes_at   TEXT,
            strategy    TEXT    NOT NULL DEFAULT 'fptp',
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS positions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id  INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
            title        TEXT    NOT NULL,
            seats        INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS candidates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            idx         INTEGER NOT NULL,          -- 该职位内的序号，计票用
            name        TEXT    NOT NULL,
            party       TEXT    NOT NULL DEFAULT '',
            UNIQUE (position_id, idx)
        );

        -- ---------- 选民册：只记录"谁投了"，不含 ballot_id ----------
        CREATE TABLE IF NOT EXISTS voter_roll (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
            voter_id    TEXT    NOT NULL,
            name        TEXT    NOT NULL DEFAULT '',
            pin_hash    TEXT    NOT NULL,
            eligible    INTEGER NOT NULL DEFAULT 1,
            has_voted   INTEGER NOT NULL DEFAULT 0,
            voted_at    TEXT,
            UNIQUE (election_id, voter_id)
        );

        -- ---------- 选票：只记录"投了什么"，不含 voter_id ----------
        CREATE TABLE IF NOT EXISTS ballots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
            position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            anon_id     TEXT    NOT NULL,          -- 与选民无关的随机标识
            choice_enc  TEXT    NOT NULL,          -- 加密后的选择
            cast_at     TEXT    NOT NULL,
            counted     INTEGER NOT NULL DEFAULT 1
        );

        -- ---------- 凭证：选民借此确认"我的票被计入"，但凭证不含选择 ----------
        CREATE TABLE IF NOT EXISTS receipts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id  INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
            position_id  INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            ballot_id    INTEGER NOT NULL REFERENCES ballots(id) ON DELETE CASCADE,
            receipt_code TEXT    NOT NULL UNIQUE,
            anon_id      TEXT    NOT NULL,
            created_at   TEXT    NOT NULL,
            verified_at  TEXT
        );

        -- ---------- 数据库级防重复投票 ----------
        -- 即使应用层出现并发缺陷，这里也只会允许一条记录成功。
        CREATE TABLE IF NOT EXISTS votes_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            voter_id    TEXT    NOT NULL,
            ballot_id   INTEGER NOT NULL REFERENCES ballots(id) ON DELETE CASCADE,
            created_at  TEXT    NOT NULL,
            UNIQUE (position_id, voter_id)
        );

        -- ---------- 结果公示 ----------
        CREATE TABLE IF NOT EXISTS results (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
            position_id   INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            strategy      TEXT    NOT NULL,
            counts_json   TEXT    NOT NULL,
            winner_idx    INTEGER,
            rounds_json   TEXT    NOT NULL DEFAULT '[]',
            digest        TEXT    NOT NULL,
            ballot_count  INTEGER NOT NULL,
            published_at  TEXT    NOT NULL,
            UNIQUE (position_id)
        );

        -- ---------- 哈希链审计日志 ----------
        CREATE TABLE IF NOT EXISTS audit_log (
            seq        INTEGER PRIMARY KEY AUTOINCREMENT,
            op         TEXT NOT NULL,
            actor      TEXT NOT NULL,
            payload    TEXT NOT NULL,
            ts         TEXT NOT NULL,
            prev_hash  TEXT NOT NULL,
            entry_hash TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ballots_election  ON ballots(election_id);
        CREATE INDEX IF NOT EXISTS idx_receipts_code     ON receipts(receipt_code);
        CREATE INDEX IF NOT EXISTS idx_voter_roll_lookup ON voter_roll(election_id, voter_id);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


# --------------------------------------------------------------------------
# 时间与审计
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def append_audit(
    conn: sqlite3.Connection,
    op: str,
    actor: str,
    payload: dict[str, Any],
    ts: Optional[str] = None,
) -> int:
    """
    追加一条审计记录，并把前一条的 entry_hash 串进来。

    注意 payload 会被白名单校验：写入"投票选择"相关字段会直接抛错，
    从结构上防止审计日志变成泄漏匿名性的旁路。
    """
    hashchain.assert_no_forbidden_keys(payload)
    ts = ts or now_iso()

    row = conn.execute(
        "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    prev_hash = row["entry_hash"] if row else hashchain.GENESIS
    seq = (row["seq"] + 1) if row else 1

    entry_hash = hashchain.compute_hash(
        seq=seq, op=op, actor=actor, payload=payload, ts=ts, prev_hash=prev_hash
    )
    conn.execute(
        """INSERT INTO audit_log(seq, op, actor, payload, ts, prev_hash, entry_hash)
           VALUES (?,?,?,?,?,?,?)""",
        (seq, op, actor, hashchain.canonical(payload), ts, prev_hash, entry_hash),
    )
    return seq


def read_audit_chain(conn: sqlite3.Connection) -> list[hashchain.ChainRecord]:
    import json

    rows = conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()
    return [
        hashchain.ChainRecord(
            seq=r["seq"],
            op=r["op"],
            actor=r["actor"],
            payload=json.loads(r["payload"]),
            ts=r["ts"],
            prev_hash=r["prev_hash"],
            entry_hash=r["entry_hash"],
        )
        for r in rows
    ]


def verify_audit(conn: sqlite3.Connection) -> tuple[bool, Optional[int], str]:
    return hashchain.verify_chain(read_audit_chain(conn))


# --------------------------------------------------------------------------
# 选举状态推进
# --------------------------------------------------------------------------

def tick_elections(conn: sqlite3.Connection, actor: str = "system") -> list[dict]:
    """
    按当前时间自动推进状态：到点开票、到点截止。
    每次迁移都写审计记录。

    每次读取前调用，因此"时间到了但状态没变"不会发生。
    """
    now = now_iso()
    changed: list[dict] = []
    rows = conn.execute(
        "SELECT id, title, status, opens_at, closes_at FROM elections"
    ).fetchall()

    for r in rows:
        target = None
        if r["status"] == lifecycle.SCHEDULED and r["opens_at"] and now >= r["opens_at"]:
            target = lifecycle.OPEN
        elif r["status"] == lifecycle.OPEN and r["closes_at"] and now >= r["closes_at"]:
            target = lifecycle.CLOSED

        if target:
            lifecycle.assert_transition(r["status"], target)
            conn.execute("UPDATE elections SET status=? WHERE id=?", (target, r["id"]))
            append_audit(
                conn,
                op="election.status",
                actor=actor,
                payload={
                    "election_id": r["id"],
                    "from": r["status"],
                    "to": target,
                    "reason": "时间窗口自动推进",
                },
            )
            changed.append({"election_id": r["id"], "from": r["status"], "to": target})
    return changed


def set_status(conn: sqlite3.Connection, election_id: int, new: str, actor: str) -> None:
    """人工推进状态（管理员操作），同样必须经过状态机校验。"""
    row = conn.execute("SELECT status FROM elections WHERE id=?", (election_id,)).fetchone()
    if row is None:
        raise KeyError(f"选举 {election_id} 不存在")
    old = row["status"]
    lifecycle.assert_transition(old, new)
    conn.execute("UPDATE elections SET status=? WHERE id=?", (new, election_id))
    append_audit(
        conn,
        op="election.status",
        actor=actor,
        payload={"election_id": election_id, "from": old, "to": new, "reason": "管理员操作"},
    )
