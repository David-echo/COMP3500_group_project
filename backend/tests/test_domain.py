"""
领域层测试：状态机 / 计票 / 哈希链
================================

纯逻辑测试，不碰数据库与 HTTP —— 因为 domain 层不依赖框架（分层带来的可测试性）。
"""

from __future__ import annotations

import pytest

from app.domain import hashchain, lifecycle, tally


# ==========================================================================
# 状态机
# ==========================================================================

class TestLifecycle:
    @pytest.mark.parametrize(
        "old,new,allowed",
        [
            ("scheduled", "open", True),
            ("open", "closed", True),
            ("closed", "published", True),
            ("scheduled", "closed", False),
            ("open", "published", False),
            ("published", "open", False),
            ("closed", "open", False),
        ],
    )
    def test_transitions(self, old, new, allowed):
        assert lifecycle.can_transition(old, new) is allowed

    def test_illegal_transition_raises(self):
        with pytest.raises(lifecycle.InvalidTransition) as e:
            lifecycle.assert_transition("open", "published")
        assert "不允许" in str(e.value)

    def test_only_open_accepts_ballots(self):
        lifecycle.assert_accepts_ballots("open")
        for s in ("scheduled", "closed", "published"):
            with pytest.raises(lifecycle.ElectionNotOpen):
                lifecycle.assert_accepts_ballots(s)


# ==========================================================================
# 计票
# ==========================================================================

class TestTally:
    def test_fptp_basic(self):
        r = tally.get_strategy("fptp").tally([[0], [0], [1], [2], [0]], 3)
        assert r.counts == {0: 3, 1: 1, 2: 1}
        assert r.winner == 0

    def test_fptp_tie_has_no_winner(self):
        r = tally.get_strategy("fptp").tally([[0], [1]], 2)
        assert r.winner is None

    def test_irv_transfers_eliminated_preferences(self):
        """C 淘汰后其支持者第二偏好转移给 B，使 B 胜出（FPTP 会选 A）。"""
        ballots = [[0]] * 4 + [[1]] * 3 + [[2, 1]] * 2
        fptp = tally.get_strategy("fptp").tally(ballots, 3)
        irv = tally.get_strategy("irv").tally(ballots, 3)
        assert fptp.winner == 0
        assert irv.winner == 1
        assert len(irv.rounds) >= 2

    def test_unknown_strategy(self):
        with pytest.raises(ValueError):
            tally.get_strategy("nope")

    def test_digest_order_independent(self):
        a = tally.tally_digest("fptp", {0: 2, 1: 1}, [5, 3, 9])
        b = tally.tally_digest("fptp", {0: 2, 1: 1}, [9, 5, 3])
        assert a == b

    def test_digest_sensitive_to_counts(self):
        a = tally.tally_digest("fptp", {0: 2}, [1, 2])
        b = tally.tally_digest("fptp", {0: 3}, [1, 2])
        assert a != b


# ==========================================================================
# 哈希链
# ==========================================================================

def _rec(seq, payload, prev):
    ts = "2026-01-01T00:00:00"
    h = hashchain.compute_hash(seq, "op", "actor", payload, ts, prev)
    return hashchain.ChainRecord(seq, "op", "actor", payload, ts, prev, h)


class TestHashChain:
    def test_empty_chain_ok(self):
        ok, bad, _ = hashchain.verify_chain([])
        assert ok and bad is None

    def test_valid_chain(self):
        r1 = _rec(1, {"a": 1}, hashchain.GENESIS)
        r2 = _rec(2, {"a": 2}, r1.entry_hash)
        ok, bad, _ = hashchain.verify_chain([r1, r2])
        assert ok and bad is None

    def test_tampered_payload_detected(self):
        r1 = _rec(1, {"a": 1}, hashchain.GENESIS)
        r2 = _rec(2, {"a": 2}, r1.entry_hash)
        tampered = hashchain.ChainRecord(
            r2.seq, r2.op, r2.actor, {"a": 999}, r2.ts, r2.prev_hash, r2.entry_hash
        )
        ok, bad, msg = hashchain.verify_chain([r1, tampered])
        assert not ok and bad == 2 and "篡改" in msg

    def test_deleted_record_detected(self):
        r1 = _rec(1, {"a": 1}, hashchain.GENESIS)
        r2 = _rec(2, {"a": 2}, r1.entry_hash)
        r3 = _rec(3, {"a": 3}, r2.entry_hash)
        ok, bad, msg = hashchain.verify_chain([r1, r3])
        assert not ok and "序号不连续" in msg

    def test_forbidden_choice_field_rejected(self):
        with pytest.raises(ValueError):
            hashchain.assert_no_forbidden_keys({"choice": [1]})

    def test_identity_plus_ballot_link_rejected(self):
        """同条记录同时出现选民身份与选票标识 → 拒绝写入。"""
        with pytest.raises(ValueError):
            hashchain.assert_no_forbidden_keys(
                {"user_id": 1, "ballot_id": 42}
            )
        with pytest.raises(ValueError):
            hashchain.assert_no_forbidden_keys(
                {"user_id": 1, "receipt_code": "ABCD-EFGH-JKLM"}
            )

    def test_ballot_link_alone_allowed(self):
        """无身份字段的 ballot_id（如 tally.ballot_rejected）是匿名的，允许。"""
        hashchain.assert_no_forbidden_keys(
            {"ballot_id": 42, "position_id": 1, "reason": "密文校验失败"}
        )

    def test_identity_plus_nested_ballot_link_rejected(self):
        """关联字段藏在嵌套结构里也要被抓住。"""
        with pytest.raises(ValueError):
            hashchain.assert_no_forbidden_keys(
                {"user_id": 1, "detail": {"refs": [{"anon_id": "abc"}]}}
            )
