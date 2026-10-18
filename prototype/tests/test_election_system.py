"""
测试套件 (Test suite)
=====================

这是本项目相对"原型"的核心差异：**工程化的质量保证**。
覆盖课程 Topic 8 (Software testing) 的三类层次：

  开发测试   : 单元测试（状态机 / 计票 / 哈希链）
  性质测试   : 核心不变量，对大量随机输入必须恒成立
  并发测试   : 真实多线程竞争同一选民，证明"防重复投票"不是纸面承诺

运行:
    python3 -m pytest tests/ -v
    python3 -m pytest tests/ -v -k concurrency     # 只看并发测试
"""

from __future__ import annotations

import base64
import os
import random
import sqlite3
import sys
import threading

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

import crypto          # noqa: E402
import db              # noqa: E402
import seed as seed_module   # noqa: E402
import service         # noqa: E402
from domain import hashchain, lifecycle, tally   # noqa: E402


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture()
def key() -> bytes:
    return crypto.derive_key(b"unit-test-master-key", "ballot-master")


@pytest.fixture()
def conn(tmp_path, key):
    """每个测试一个全新的数据库文件（真实文件，不是内存库），
    这样并发测试才有多连接争锁的真实语义。"""
    path = str(tmp_path / "test.db")
    c = db.connect(path)
    db.migrate(c)
    yield c
    c.close()


@pytest.fixture()
def scenario(conn, key):
    """最小场景：1 场进行中的选举，1 个职位，3 名候选，5 名选民。"""
    eid = conn.execute(
        """INSERT INTO elections(title, description, status, opens_at, closes_at, strategy, created_at)
           VALUES ('测试选举','', 'open', '2020-01-01T00:00:00','2099-01-01T00:00:00','fptp',?)""",
        (db.now_iso(),),
    ).lastrowid
    pid = conn.execute(
        "INSERT INTO positions(election_id, title, seats) VALUES (?,?,1)", (eid, "主席")
    ).lastrowid
    for idx, name in enumerate(["甲", "乙", "丙"]):
        conn.execute(
            "INSERT INTO candidates(position_id, idx, name, party) VALUES (?,?,?,'')",
            (pid, idx, name),
        )
    voters = []
    pin = seed_module._pin_hash("1234")
    for i in range(5):
        vid = f"V{i:03d}"
        conn.execute(
            """INSERT INTO voter_roll(election_id, voter_id, name, pin_hash, eligible, has_voted)
               VALUES (?,?,?,?,1,0)""",
            (eid, vid, f"选民{i}", pin),
        )
        voters.append(vid)
    conn.commit()
    return {"election_id": eid, "position_id": pid, "voters": voters}


# ==========================================================================
# 一、哈希链单元测试
# ==========================================================================

class TestHashChain:
    def test_empty_chain_is_valid(self):
        ok, bad, _ = hashchain.verify_chain([])
        assert ok and bad is None

    def test_chain_grows_and_verifies(self, conn):
        for i in range(5):
            db.append_audit(conn, op="test.op", actor="tester", payload={"i": i})
        conn.commit()
        ok, bad, msg = db.verify_audit(conn)
        assert ok, msg
        assert len(db.read_audit_chain(conn)) == 5

    def test_tamper_on_payload_is_detected(self, conn):
        for i in range(6):
            db.append_audit(conn, op="test.op", actor="tester", payload={"i": i})
        conn.commit()

        # 攻击者直接改数据库里第 3 条的 payload
        conn.execute(
            "UPDATE audit_log SET payload=? WHERE seq=3",
            (hashchain.canonical({"i": 999}),),
        )
        conn.commit()

        ok, bad, msg = db.verify_audit(conn)
        assert not ok, "篡改 payload 必须被发现"
        assert bad == 3, f"应定位到 seq=3，实际 {bad}"
        assert "篡改" in msg or "不符" in msg

    def test_tamper_on_op_is_detected(self, conn):
        for i in range(4):
            db.append_audit(conn, op="test.op", actor="tester", payload={"i": i})
        conn.commit()
        conn.execute("UPDATE audit_log SET op='innocent.op' WHERE seq=2")
        conn.commit()
        ok, bad, _ = db.verify_audit(conn)
        assert not ok and bad == 2

    def test_deleting_a_record_is_detected(self, conn):
        """删记录会造成序号不连续，必须被发现。"""
        for i in range(5):
            db.append_audit(conn, op="test.op", actor="tester", payload={"i": i})
        conn.commit()
        conn.execute("DELETE FROM audit_log WHERE seq=3")
        conn.commit()
        ok, bad, msg = db.verify_audit(conn)
        assert not ok
        assert "序号不连续" in msg

    def test_forbidden_keys_rejected(self, conn):
        """审计日志绝不允许写入投票选择 —— 否则匿名性会被日志泄漏。"""
        with pytest.raises(ValueError) as e:
            db.append_audit(conn, op="ballot.cast", actor="x", payload={"choice": [1]})
        assert "匿名性" in str(e.value) or "禁止" in str(e.value)

    def test_hash_is_deterministic(self):
        args = dict(seq=1, op="o", actor="a", payload={"b": 1, "a": 2},
                    ts="2026-01-01T00:00:00", prev_hash=hashchain.GENESIS)
        assert hashchain.compute_hash(**args) == hashchain.compute_hash(**args)

    def test_key_order_does_not_change_hash(self):
        """canonical() 必须与字典插入顺序无关，否则链会误报。"""
        h1 = hashchain.compute_hash(1, "o", "a", {"x": 1, "y": 2}, "t", hashchain.GENESIS)
        h2 = hashchain.compute_hash(1, "o", "a", {"y": 2, "x": 1}, "t", hashchain.GENESIS)
        assert h1 == h2


# ==========================================================================
# 二、状态机单元测试
# ==========================================================================

class TestLifecycle:
    @pytest.mark.parametrize("old,new,allowed", [
        ("scheduled", "open", True),
        ("open", "closed", True),
        ("closed", "published", True),
        ("scheduled", "closed", False),      # 跳过投票阶段
        ("open", "published", False),        # 跳过截止
        ("published", "open", False),        # 终态不可回退
        ("closed", "open", False),           # 不可重新开启
        ("published", "closed", False),
    ])
    def test_transitions(self, old, new, allowed):
        assert lifecycle.can_transition(old, new) is allowed

    def test_assert_transition_raises_on_illegal(self):
        with pytest.raises(lifecycle.InvalidTransition) as e:
            lifecycle.assert_transition("open", "published")
        assert "不允许" in str(e.value)

    def test_only_open_accepts_ballots(self):
        lifecycle.assert_accepts_ballots("open")   # 不抛异常
        for s in ("scheduled", "closed", "published"):
            with pytest.raises(lifecycle.ElectionClosed):
                lifecycle.assert_accepts_ballots(s)


# ==========================================================================
# 三、投票业务测试
# ==========================================================================

class TestCastBallot:
    def test_happy_path_creates_ballot_log_receipt(self, conn, key, scenario):
        out = service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"],
            scenario["voters"][0], [1],
        )
        assert out.receipt_code.count("-") == 2
        pid = scenario["position_id"]
        assert conn.execute("SELECT COUNT(*) c FROM ballots WHERE position_id=?", (pid,)).fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM votes_log WHERE position_id=?", (pid,)).fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM receipts WHERE position_id=?", (pid,)).fetchone()["c"] == 1
        # 选民册被标记，且**没有**记录 ballot_id
        row = conn.execute(
            "SELECT has_voted FROM voter_roll WHERE election_id=? AND voter_id=?",
            (scenario["election_id"], scenario["voters"][0]),
        ).fetchone()
        assert row["has_voted"] == 1
        cols = {r[1] for r in conn.execute("PRAGMA table_info(voter_roll)")}
        assert "ballot_id" not in cols, "选民册不得保存选票外键（会破坏匿名性）"

    def test_duplicate_vote_rejected(self, conn, key, scenario):
        args = (conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0])
        service.cast_ballot(*args, [0])
        with pytest.raises(service.VoteError) as e:
            service.cast_ballot(*args, [2])
        assert "重复" in str(e.value)
        assert conn.execute("SELECT COUNT(*) c FROM ballots").fetchone()["c"] == 1

    def test_out_of_range_choice_rejected(self, conn, key, scenario):
        with pytest.raises(service.VoteError) as e:
            service.cast_ballot(
                conn, key, scenario["election_id"], scenario["position_id"],
                scenario["voters"][1], [99],
            )
        assert "越界" in str(e.value)

    def test_empty_choice_rejected(self, conn, key, scenario):
        with pytest.raises(service.VoteError):
            service.cast_ballot(
                conn, key, scenario["election_id"], scenario["position_id"],
                scenario["voters"][1], [],
            )

    def test_non_eligible_voter_rejected(self, conn, key, scenario):
        conn.execute(
            "UPDATE voter_roll SET eligible=0 WHERE election_id=? AND voter_id=?",
            (scenario["election_id"], scenario["voters"][2]),
        )
        conn.commit()
        with pytest.raises(service.VoteError) as e:
            service.cast_ballot(
                conn, key, scenario["election_id"], scenario["position_id"],
                scenario["voters"][2], [0],
            )
        assert "资格" in str(e.value)

    def test_unknown_voter_rejected(self, conn, key, scenario):
        with pytest.raises(service.VoteError) as e:
            service.cast_ballot(
                conn, key, scenario["election_id"], scenario["position_id"], "NOT-A-VOTER", [0],
            )
        assert "名册" in str(e.value)

    def test_vote_on_non_open_election_rejected(self, conn, key, scenario):
        conn.execute("UPDATE elections SET status='closed' WHERE id=?", (scenario["election_id"],))
        conn.commit()
        with pytest.raises(lifecycle.ElectionClosed):
            service.cast_ballot(
                conn, key, scenario["election_id"], scenario["position_id"],
                scenario["voters"][3], [0],
            )
        assert conn.execute("SELECT COUNT(*) c FROM ballots").fetchone()["c"] == 0

    def test_ballot_does_not_contain_voter_id(self, conn, key, scenario):
        """结构性匿名性：ballots 表里根本没有 voter_id 字段。"""
        service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0], [1],
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ballots)")}
        assert "voter_id" not in cols
        assert "anon_id" in cols

    def test_choice_is_encrypted_at_rest(self, conn, key, scenario):
        """
        数据库里不应出现明文选择。

        注意断言写法：不能在 base64 密文里搜 "2" —— base64 字母表本身就含
        数字 2，那种断言会随机失败（这是本测试第一版犯过的错）。
        正确做法是解码后检查明文载荷确实不等于原始选择。
        """
        service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0], [2, 1],
        )
        blob = conn.execute("SELECT choice_enc FROM ballots").fetchone()["choice_enc"]

        # ① 明文载荷 "2,1" 不应出现在解码后的字节里
        raw = base64.b64decode(blob)
        assert b"2,1" not in raw, "解码后的密文中出现了明文选择"

        # ② 密文可被正确解密（证明加密是可靠往返的）
        auth_key = crypto.derive_key(key, "ballot-auth")
        assert crypto.decrypt_choice(auth_key, blob) == [2, 1]

        # ③ 加密是随机的：同样内容两次加密结果不同（nonce 生效）
        assert crypto.encrypt_choice(auth_key, [2, 1]) != crypto.encrypt_choice(auth_key, [2, 1])

    def test_receipt_reveals_no_choice(self, conn, key, scenario):
        """
        凭证核验结果**必须**不包含任何可推断选择的字段 ——
        否则凭证就变成了"可以向第三方证明我投了谁"的工具，为贿选留门。
        """
        out = service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0], [1],
        )
        res = service.verify_receipt(conn, out.receipt_code)
        assert res["found"] and res["counted"]
        forbidden = {"choice", "choice_enc", "candidate", "candidate_id", "voted_for", "idx"}
        assert not forbidden.intersection(res.keys())

    def test_receipt_unknown_code(self, conn):
        assert service.verify_receipt(conn, "AAAA-BBBB-CCCC")["found"] is False

    def test_tampered_ciphertext_rejected(self, conn, key, scenario):
        service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0], [1],
        )
        conn.execute("UPDATE ballots SET choice_enc='AAAA' WHERE id=1")
        conn.commit()
        with pytest.raises(ValueError):
            crypto.decrypt_choice(crypto.derive_key(key, "ballot-auth"),
                                  conn.execute("SELECT choice_enc FROM ballots").fetchone()["choice_enc"])


# ==========================================================================
# 四、计票测试
# ==========================================================================

class TestTally:
    def test_fptp_basic(self):
        r = tally.get_strategy("fptp").tally([[0], [0], [1], [2], [0]], 3)
        assert r.counts == {0: 3, 1: 1, 2: 1}
        assert r.winner == 0

    def test_fptp_tie_has_no_winner(self):
        r = tally.get_strategy("fptp").tally([[0], [1]], 2)
        assert r.winner is None
        assert "并列" in r.note

    def test_irv_majority_first_round(self):
        r = tally.get_strategy("irv").tally([[0], [0], [0], [1], [2]], 3)
        assert r.winner == 0
        assert "过半数" in r.note

    def test_irv_transfers_eliminated_preferences(self):
        """
        经典 IRV 场景：C 淘汰后，其支持者的第二偏好转移到 B，使 B 胜出。
        若按单选制，A 会以 4:3:2 胜出 —— 这正是"计票策略可插拔"的价值。
        """
        ballots = [[0]]*4 + [[1]]*3 + [[2, 1]]*2
        fptp = tally.get_strategy("fptp").tally(ballots, 3)
        irv = tally.get_strategy("irv").tally(ballots, 3)
        assert fptp.winner == 0
        assert irv.winner == 1, f"IRV 应把 C 的票转移给 B，实际 {irv}"
        assert len(irv.rounds) >= 2

    def test_irv_exhausted_ballots_counted(self):
        r = tally.get_strategy("irv").tally([[0], [0], [1, 2], [2, 1]], 3)
        assert r.rounds[0]["exhausted"] >= 0

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError):
            tally.get_strategy("nope")

    def test_digest_is_order_independent(self):
        """摘要必须与选票顺序无关，否则第三方复算无法比对。"""
        d1 = tally.tally_digest("fptp", {0: 2, 1: 1}, [5, 3, 9])
        d2 = tally.tally_digest("fptp", {0: 2, 1: 1}, [9, 5, 3])
        assert d1 == d2

    def test_digest_changes_if_counts_change(self):
        d1 = tally.tally_digest("fptp", {0: 2, 1: 1}, [1, 2, 3])
        d2 = tally.tally_digest("fptp", {0: 3, 1: 1}, [1, 2, 3])
        assert d1 != d2


# ==========================================================================
# 五、不变量 / 性质测试
# ==========================================================================

class TestInvariants:
    def test_invariants_hold_after_random_voting(self, conn, key, scenario):
        """
        性质测试：任意随机投票序列之后，"选票数 == 投票记录数 == 凭证数"
        以及"已投票人数 == 投票记录数"必须恒成立。
        """
        rng = random.Random(7)
        pid = scenario["position_id"]
        eid = scenario["election_id"]

        # 扩到 40 名选民，随机投 0~1 次
        pin = seed_module._pin_hash("1234")
        for i in range(100, 140):
            conn.execute(
                """INSERT INTO voter_roll(election_id, voter_id, name, pin_hash, eligible, has_voted)
                   VALUES (?,?,?,?,1,0)""", (eid, f"V{i}", f"选民{i}", pin),
            )
        conn.commit()

        for i in list(range(100, 140)):
            if rng.random() < 0.75:
                try:
                    service.cast_ballot(conn, key, eid, pid, f"V{i}", [rng.randrange(3)])
                except service.VoteError:
                    pass

        res = service.check_invariants(conn, eid)
        assert res["all_passed"], res
        for c in res["checks"]:
            assert c["passed"], c

    def test_invariants_hold_for_seeded_dataset(self, tmp_path, key):
        """完整种子数据集也必须通过全部不变量。"""
        c = db.connect(str(tmp_path / "seeded.db"))
        db.migrate(c)
        seed_module.seed(c, key)
        for e in c.execute("SELECT id FROM elections").fetchall():
            res = service.check_invariants(c, e["id"])
            assert res["all_passed"], (e["id"], res)
        c.close()

    def test_seeded_audit_chain_is_valid(self, tmp_path, key):
        c = db.connect(str(tmp_path / "seeded2.db"))
        db.migrate(c)
        seed_module.seed(c, key)
        ok, bad, msg = db.verify_audit(c)
        assert ok, msg
        c.close()


# ==========================================================================
# 六、并发测试 —— 本项目最有说服力的一组测试
# ==========================================================================

class TestConcurrency:
    def test_concurrent_duplicate_votes_only_one_succeeds(self, conn, key, scenario, tmp_path):
        """
        20 个线程同时对**同一个选民、同一个职位**投票。

        期望：恰好 1 个成功，19 个收到"重复投票"错误。
        这正是物流原型缺失的那类保证 —— 那里 dispatch 可以无视状态直接改状态。
        """
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        pid = scenario["position_id"]
        eid = scenario["election_id"]
        voter = scenario["voters"][0]

        results: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(20)

        def worker(i: int):
            c = db.connect(db_path)          # 每个线程独立连接（真实并发）
            try:
                barrier.wait(timeout=10)     # 尽量让竞争同时发生
                try:
                    service.cast_ballot(c, key, eid, pid, voter, [i % 3])
                    with lock:
                        results.append("ok")
                except service.VoteError as e:
                    with lock:
                        results.append("dup" if "重复" in str(e) else f"other:{e}")
                except sqlite3.OperationalError as e:
                    with lock:
                        results.append(f"locked:{e}")
            finally:
                c.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        ok_n = results.count("ok")
        assert ok_n == 1, f"并发下必须恰好 1 票成功，实际 {ok_n}（{results}）"
        assert len(results) == 20

        check = db.connect(db_path)
        try:
            assert check.execute(
                "SELECT COUNT(*) c FROM ballots WHERE position_id=?", (pid,)
            ).fetchone()["c"] == 1
            assert check.execute(
                "SELECT COUNT(*) c FROM votes_log WHERE position_id=?", (pid,)
            ).fetchone()["c"] == 1
            assert check.execute(
                "SELECT COUNT(*) c FROM receipts WHERE position_id=?", (pid,)
            ).fetchone()["c"] == 1
        finally:
            check.close()

    def test_concurrent_distinct_voters_all_succeed(self, conn, key, scenario):
        """不同选民并发投票应当全部成功 —— 证明上面的限制不是"过度加锁"。"""
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        pid, eid = scenario["position_id"], scenario["election_id"]
        pin = seed_module._pin_hash("1234")
        voters = []
        for i in range(200, 220):
            conn.execute(
                """INSERT INTO voter_roll(election_id, voter_id, name, pin_hash, eligible, has_voted)
                   VALUES (?,?,?,?,1,0)""", (eid, f"V{i}", f"选民{i}", pin),
            )
            voters.append(f"V{i}")
        conn.commit()

        results: list[str] = []
        lock = threading.Lock()
        barrier = threading.Barrier(len(voters))

        def worker(vid: str):
            c = db.connect(db_path)
            try:
                barrier.wait(timeout=10)
                try:
                    service.cast_ballot(c, key, eid, pid, vid, [0])
                    with lock:
                        results.append("ok")
                except Exception as e:
                    with lock:
                        results.append(f"err:{e}")
            finally:
                c.close()

        threads = [threading.Thread(target=worker, args=(v,)) for v in voters]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert results.count("ok") == len(voters), results
        res = service.check_invariants(conn, eid)
        assert res["all_passed"], res


# ==========================================================================
# 七、计票端到端
# ==========================================================================

class TestPublish:
    def test_publish_requires_closed(self, conn, key, scenario):
        with pytest.raises(service.VoteError) as e:
            service.publish_results(conn, key, scenario["election_id"], actor="admin")
        assert "进行中" in str(e.value)

    def test_publish_after_close_and_status_becomes_published(self, conn, key, scenario):
        for i, v in enumerate(scenario["voters"]):
            service.cast_ballot(conn, key, scenario["election_id"], scenario["position_id"], v, [i % 3])
        conn.execute("UPDATE elections SET status='closed' WHERE id=?", (scenario["election_id"],))
        conn.commit()

        out = service.publish_results(conn, key, scenario["election_id"], actor="admin")
        assert out["already_published"] is False
        res = out["results"][0]
        assert res["ballot_count"] == 5
        assert sum(res["counts"].values()) == 5
        assert len(res["digest"]) == 64

        status = conn.execute(
            "SELECT status FROM elections WHERE id=?", (scenario["election_id"],)
        ).fetchone()["status"]
        assert status == "published"

    def test_publish_is_idempotent(self, conn, key, scenario):
        service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0], [0],
        )
        conn.execute("UPDATE elections SET status='closed' WHERE id=?", (scenario["election_id"],))
        conn.commit()
        first = service.publish_results(conn, key, scenario["election_id"], actor="admin")
        second = service.publish_results(conn, key, scenario["election_id"], actor="admin")
        assert first["already_published"] is False
        assert second["already_published"] is True
        assert second["results"][0]["digest"] == first["results"][0]["digest"]

    def test_voting_after_publish_is_rejected(self, conn, key, scenario):
        service.cast_ballot(
            conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][0], [0],
        )
        conn.execute("UPDATE elections SET status='closed' WHERE id=?", (scenario["election_id"],))
        conn.commit()
        service.publish_results(conn, key, scenario["election_id"], actor="admin")
        with pytest.raises(lifecycle.ElectionClosed):
            service.cast_ballot(
                conn, key, scenario["election_id"], scenario["position_id"], scenario["voters"][1], [1],
            )


# ==========================================================================
# 八、HTTP 层（端到端）
# ==========================================================================

class TestHttp:
    @pytest.fixture()
    def client(self, tmp_path, key):
        import app as appmod
        application = appmod.create_app(
            DB_PATH=str(tmp_path / "http.db"),
            SECRET_PATH=str(tmp_path / "http.key"),
            TESTING=True,
        )
        with application.app_context():
            c = db.connect(application.config["DB_PATH"])
            db.migrate(c)
            seed_module.seed(c, key)
            c.close()
        return application.test_client()

    def test_health_reports_intact_chain(self, client):
        h = client.get("/api/health").get_json()
        assert h["status"] == "ok"
        assert h["audit_chain_ok"] is True
        assert h["counts"]["ballots"] > 0

    def test_login_and_vote_and_receipt_flow(self, client):
        pool = client.get("/api/demo/voters").get_json()
        vid = pool["voters"][0]["voter_id"]

        # 登录不再需要先选选举
        r = client.post("/api/login", json={"role": "voter", "username": vid, "pin": "1234"})
        assert r.status_code == 200, r.get_json()
        user = r.get_json()["user"]
        assert "elections" in user and user["elections"], "登录后应返回可参与的选举列表"

        # 找到该选民可投票的进行中选举
        me = client.get("/api/me").get_json()["user"]
        target = next(e for e in me["elections"] if e["status"] == "open" and not e["has_voted"])
        eid = target["election_id"]
        pos = next(e for e in client.get("/api/elections").get_json()["elections"]
                   if e["id"] == eid)["positions"][0]["position_id"]

        r = client.post("/api/vote", json={"election_id": eid, "position_id": pos, "choice": [1]})
        assert r.status_code == 200, r.get_json()
        code = r.get_json()["receipt_code"]

        # 重复投票被拒
        assert client.post("/api/vote",
                           json={"election_id": eid, "position_id": pos, "choice": [0]}).status_code == 400
        assert client.get(f"/api/receipt/{code}").get_json()["counted"] is True

    def test_login_does_not_require_election(self, client):
        """回归测试：登录接口不得强制要求 election_id（旧版会返回 400）。"""
        pool = client.get("/api/demo/voters").get_json()
        vid = pool["voters"][0]["voter_id"]
        r = client.post("/api/login", json={"role": "voter", "username": vid, "pin": "1234"})
        assert r.status_code == 200

    def test_vote_requires_roster_membership(self, client):
        """不能投自己名册以外的选举。"""
        pool = client.get("/api/demo/voters").get_json()
        vid = pool["voters"][0]["voter_id"]
        client.post("/api/login", json={"role": "voter", "username": vid, "pin": "1234"})
        r = client.post("/api/vote", json={"election_id": 999, "position_id": 1, "choice": [0]})
        assert r.status_code == 403

    def test_demo_pool_has_at_least_five_available(self, client):
        """每个进行中的选举都应有足够的可投票选民，方便现场多人测试。"""
        pool = client.get("/api/demo/voters").get_json()
        assert pool["voter_count"] >= 5, pool
        assert len(pool["voters"]) >= 5

    def test_wrong_pin_rejected(self, client):
        pool = client.get("/api/demo/voters").get_json()
        vid = pool["voters"][0]["voter_id"]
        r = client.post("/api/login", json={"role": "voter", "username": vid, "pin": "wrong"})
        assert r.status_code == 401

    def test_results_hidden_while_open(self, client):
        r = client.get("/api/results/1").get_json()
        assert r["published"] is False

    def test_admin_required_for_status_change(self, client):
        assert client.post("/api/admin/status",
                           json={"election_id": 1, "status": "closed"}).status_code == 403
        client.post("/api/login", json={"role": "admin", "username": "admin", "pin": "admin123"})
        assert client.post("/api/admin/status",
                           json={"election_id": 1, "status": "closed"}).status_code == 200
        # 非法迁移必须被拒
        r = client.post("/api/admin/status", json={"election_id": 1, "status": "open"})
        assert r.status_code == 400

    def test_tamper_demo_breaks_then_restores_chain(self, client):
        assert client.get("/api/audit/verify").get_json()["ok"] is True

        t = client.post("/api/demo/tamper", json={"token": "TAMPER-DEMO-2026"}).get_json()
        assert t["chain_ok"] is False
        assert t["first_bad_seq"] is not None

        after = client.get("/api/audit/verify").get_json()
        assert after["ok"] is False
        assert after["first_bad_seq"] == t["tampered_seq"]

        client.post("/api/demo/tamper", json={"token": "TAMPER-DEMO-2026", "restore": True})
        assert client.get("/api/audit/verify").get_json()["ok"] is True

    def test_tamper_requires_token(self, client):
        assert client.post("/api/demo/tamper", json={}).status_code == 403
