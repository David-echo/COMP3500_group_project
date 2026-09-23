"""
种子数据 (Seed data)
====================

生成一个可直接演示的完整数据集：
  - 4 场不同状态的选举：进行中 / 未开始 / 已截止 / 已公布
  - 演示「排名复选制 (IRV)」的排序选票
  - 大量预投选票，让看板与完整性校验有真实内容

所有预投票都走 service.cast_ballot()，因此审计哈希链是真实完整的，
而不是伪造的日志 —— 这一点很重要：篡改演练必须建立在真实链上才有说服力。
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta

import crypto
import db
import service

# 演示用账号
ADMIN_USER = "admin"
ADMIN_PIN = "admin123"
VOTER_PIN = "1234"

VOTER_SURNAMES = "陈李黄何周张刘吴蔡杨许郑谢郭洪曾朱罗梁宋"

# 保证每个"进行中"的选举至少保留这么多未投票的选民，方便现场多人轮流测试
MIN_AVAILABLE_VOTERS = 5


def _vid(prefix: str, i: int) -> str:
    """统一生成选民编号，例如 HK、HK100042。"""
    return f"{prefix}{100000 + i}"


def _voter_ids(n: int, prefix: str = "HK") -> list[str]:
    return [_vid(prefix, i) for i in range(n)]


def _pin_hash(pin: str) -> str:
    from werkzeug.security import generate_password_hash

    return generate_password_hash(pin)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def is_seeded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) AS c FROM elections").fetchone()["c"] > 0


def seed(conn: sqlite3.Connection, ballot_key: bytes, rng_seed: int = 42) -> dict:
    """建立完整演示数据。假定数据库为空。"""
    rng = random.Random(rng_seed)
    now = datetime.now()

    # ---------------- 1. 进行中的选举 ----------------
    e1 = _create_election(
        conn,
        title="2026 学生事务委员会主席选举",
        description="投票进行中。可以现场投票、核验凭证、尝试重复投票。",
        status="open",
        opens_at=_iso(now - timedelta(hours=6)),
        closes_at=_iso(now + timedelta(days=2)),
        strategy="fptp",
    )
    p1 = _create_position(conn, e1, "主席 (Chairperson)")
    c1 = _create_candidates(
        conn,
        p1,
        [
            ("陈嘉禾", "学生会"),
            ("李浩然", "独立"),
            ("黄敏怡", "学生会"),
            ("何俊杰", "独立"),
            ("周咏诗", "学生会"),
        ],
    )
    # 60 名选民；先投 35 票，**刻意保留 25 名未投票**供现场测试
    voters1 = _create_voters(conn, e1, [_vid("HK", i) for i in range(60)])
    _precast(conn, ballot_key, e1, p1, voters1[:35], n=35, rng=rng, ranked=False)

    # ---------------- 2. 未开始的选举（演示自动开票） ----------------
    # 同样要录入选民：否则选举 #2 会出现"0/0 投票率"，且开票后无人可投。
    # 注意生命周期顺序：状态机**拒绝**对 scheduled 选举投票，
    # 所以必须先建成 open 才能预投；预投完毕后再把状态退回 scheduled
    # （见文件末尾的 UPDATE），从而真实地表达"这是一场还没开始的选举"。
    e2 = _create_election(
        conn,
        title="2026 校董会学生代表选举",
        description="尚未开始。到 opens_at 后由系统自动进入投票状态（演示状态机自动推进）。",
        status="open",
        opens_at=_iso(now + timedelta(minutes=3)),
        closes_at=_iso(now + timedelta(days=3)),
        strategy="fptp",
    )
    p2 = _create_position(conn, e2, "学生代表")
    _create_candidates(
        conn,
        p2,
        [("吴卓颖", "研究生会"), ("郑家豪", "本科生会"), ("谢婉玲", "独立")],
    )
    # 独立的选民号段：这些选民与选举 1 的选民是不同的人
    voters2 = _create_voters(conn, e2, [_vid("HK", i) for i in range(200, 215)])
    # 投 10 票，保留 5 个全新选民，用于演示"开票后可立即投票"
    _precast(conn, ballot_key, e2, p2, voters2[:10], n=10, rng=rng, ranked=False)

    # ---------------- 3. 已截止、待计票（演示 IRV 排序复选制） ----------------
    # 注意：这里先建成 open 并投票，再让 tick_elections() 依据 closes_at
    # 自动推进到 closed —— 状态机拒绝"对 closed 选举投票"，
    # 所以必须走真实的生命周期，而不能直接把状态写成 closed。
    e3 = _create_election(
        conn,
        title="2026 环保政策咨询公投（排序复选）",
        description="已截止，等待计票。本场采用排序复选制 (IRV)，用于演示计票策略的可插拔。",
        status="open",
        opens_at=_iso(now - timedelta(days=5)),
        closes_at=_iso(now - timedelta(days=1)),
        strategy="irv",
    )
    p3 = _create_position(conn, e3, "首选方案")
    _create_candidates(
        conn,
        p3,
        [
            ("方案甲：全面回收", "环保组"),
            ("方案乙：分区试点", "行政组"),
            ("方案丙：押后检讨", "财务组"),
        ],
    )
    voters3 = _create_voters(conn, e3, [_vid("EN", i) for i in range(50)])
    _precast(conn, ballot_key, e3, p3, voters3, n=44, rng=rng, ranked=True)

    # ---------------- 4. 已公布结果的选举 ----------------
    e4 = _create_election(
        conn,
        title="2025 图书馆开放时间公投",
        description="已完成计票并公示，用于演示结果与摘要哈希的展示。",
        status="open",
        opens_at=_iso(now - timedelta(days=30)),
        closes_at=_iso(now - timedelta(days=20)),
        strategy="fptp",
    )
    p4 = _create_position(conn, e4, "延长开放时间")
    _create_candidates(
        conn,
        p4,
        [("同意延长至 23:00", "提案方"), ("维持 21:00", "反对方")],
    )
    voters4 = _create_voters(conn, e4, [_vid("LB", i) for i in range(40)])
    _precast(conn, ballot_key, e4, p4, voters4, n=31, rng=rng, ranked=False)

    # 依据 closes_at 把已过窗口的选举自动推进到 closed（真实生命周期）
    db.tick_elections(conn)
    service.publish_results(conn, ballot_key, e4, actor=ADMIN_USER)

    # 选举 2 的预投票已完成，现在把状态退回 scheduled，
    # 以真实表达"这是一场尚未开始的选举"（其预投数据保持不变，
    # 并会在 opens_at 到点后被 tick_elections() 自动开票）。
    conn.execute("UPDATE elections SET status='scheduled' WHERE id=?", (e2,))
    db.append_audit(
        conn,
        op="system.seed_reset_status",
        actor="system",
        payload={"election_id": e2, "to": "scheduled", "reason": "演示数据：该场选举尚未开始"},
    )

    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('seeded_at', ?)", (db.now_iso(),)
    )
    db.append_audit(
        conn,
        op="system.seed",
        actor="system",
        payload={
            "elections": 4,
            "note": "演示数据集初始化完成",
        },
    )
    conn.commit()
    return {"elections": [e1, e3, e4], "voters": len(voters1)}


# --------------------------------------------------------------------------
# 内部辅助
# --------------------------------------------------------------------------

def _create_election(
    conn, title: str, description: str, status: str, opens_at: str, closes_at: str, strategy: str
) -> int:
    cur = conn.execute(
        """INSERT INTO elections(title, description, status, opens_at, closes_at, strategy, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (title, description, status, opens_at, closes_at, strategy, db.now_iso()),
    )
    return cur.lastrowid


def _create_position(conn, election_id: int, title: str) -> int:
    cur = conn.execute(
        "INSERT INTO positions(election_id, title, seats) VALUES (?,?,1)",
        (election_id, title),
    )
    return cur.lastrowid


def _create_candidates(conn, position_id: int, rows: list[tuple[str, str]]) -> int:
    for idx, (name, party) in enumerate(rows):
        conn.execute(
            "INSERT INTO candidates(position_id, idx, name, party) VALUES (?,?,?,?)",
            (position_id, idx, name, party),
        )
    return len(rows)


def _create_voters(conn, election_id: int, voter_ids: list[str]) -> list[dict]:
    """按给定的选民编号列表录入选民。编号由调用方决定，避免跨选举撞号。"""
    pin = _pin_hash(VOTER_PIN)
    voters = []
    for i, vid in enumerate(voter_ids):
        name = VOTER_SURNAMES[i % len(VOTER_SURNAMES)] + "先生/女士"
        conn.execute(
            """INSERT INTO voter_roll(election_id, voter_id, name, pin_hash, eligible, has_voted)
               VALUES (?,?,?,?,1,0)""",
            (election_id, vid, name, pin),
        )
        voters.append({"voter_id": vid, "name": name})
    return voters


def top_up_voters(conn: sqlite3.Connection) -> list[dict]:
    """
    为每个「进行中」的选举补齐未投票选民，直到至少有 MIN_AVAILABLE_VOTERS 名。

    用途：方便现场用多台设备 / 多个同学轮流投票测试。
    对已有数据库也安全 —— 幂等，且编号不会与既有选民冲突。
    """
    report: list[dict] = []
    pin = _pin_hash(VOTER_PIN)

    open_elections = conn.execute(
        "SELECT id, title FROM elections WHERE status='open' ORDER BY id"
    ).fetchall()

    for e in open_elections:
        available = conn.execute(
            """SELECT COUNT(*) c FROM voter_roll
                WHERE election_id=? AND has_voted=0 AND eligible=1""",
            (e["id"],),
        ).fetchone()["c"]
        need = MIN_AVAILABLE_VOTERS - available
        if need <= 0:
            report.append({"election_id": e["id"], "added": 0, "available": available})
            continue

        # 取一个不会被既有编号占用的起点
        base = conn.execute(
            "SELECT COUNT(*) c FROM voter_roll WHERE election_id=?", (e["id"],)
        ).fetchone()["c"]
        added = 0
        while added < need:
            vid = f"HK{900000 + base + added}"
            exists = conn.execute(
                "SELECT 1 FROM voter_roll WHERE election_id=? AND voter_id=?",
                (e["id"], vid),
            ).fetchone()
            if exists:
                base += 1
                continue
            conn.execute(
                """INSERT INTO voter_roll(election_id, voter_id, name, pin_hash, eligible, has_voted)
                   VALUES (?,?,?,?,1,0)""",
                (e["id"], vid, f"测试选民{added + 1}号", pin),
            )
            added += 1

        db.append_audit(
            conn,
            op="system.top_up_voters",
            actor="system",
            payload={
                "election_id": e["id"],
                "added": added,
                "available_before": available,
                "available_after": available + added,
            },
        )
        report.append(
            {"election_id": e["id"], "added": added, "available": available + added}
        )

    conn.commit()
    return report


def _precast(
    conn,
    ballot_key: bytes,
    election_id: int,
    position_id: int,
    voters: list[dict],
    n: int,
    rng: random.Random,
    ranked: bool,
) -> None:
    """预先投出 n 张选票（走真实的 service 路径，因此审计链真实）。"""
    num_candidates = conn.execute(
        "SELECT COUNT(*) AS c FROM candidates WHERE position_id=?", (position_id,)
    ).fetchone()["c"]

    chosen = rng.sample(voters, min(n, len(voters)))
    for i, v in enumerate(chosen):
        if ranked:
            order = list(range(num_candidates))
            rng.shuffle(order)
            # 让排序有倾向性，避免完全随机导致 IRV 无趣
            if rng.random() < 0.55:
                bias = rng.randrange(num_candidates)
                order.remove(bias)
                order.insert(0, bias)
            choice = order[: rng.randint(2, num_candidates)]
        else:
            # 带倾向性的单选票，使结果有区分度
            choice = [rng.choices(range(num_candidates), weights=[3, 2, 2, 1, 1][:num_candidates])[0]]

        service.cast_ballot(
            conn,
            ballot_key=ballot_key,
            election_id=election_id,
            position_id=position_id,
            voter_id=v["voter_id"],
            choice=choice,
            actor=f"seed:{v['voter_id']}",
        )
