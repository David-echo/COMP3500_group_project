"""
接口与集成测试 (API / Integration)
=================================

覆盖课程 Topic 8（软件测试）的层次：
  - 接口测试：登录、选举列表、投票、凭证核验
  - 状态门控：未截止不公开结果、截止后才能计票
  - 权限：越权访问被拒
  - 不变量：投票后各项计数一致
  - 并发：同一选民并发投票只有 1 票成功（ADR-002 的验证）
  - SSE：能建立事件流并收到首帧
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Ballot, Receipt, VotesLog

from .conftest import auth, login, make_user


# ==========================================================================
# 认证
# ==========================================================================

class TestAuth:
    async def test_register_and_login(self, client):
        r = await client.post(
            "/api/v1/auth/register",
            json={"student_id": "HK999", "name": "张三", "password": "password123"},
        )
        assert r.status_code == 201, r.text

        r = await client.post(
            "/api/v1/auth/login",
            json={"student_id": "HK999", "password": "password123"},
        )
        assert r.status_code == 200
        assert r.json()["user"]["student_id"] == "HK999"

    async def test_duplicate_student_id_rejected(self, client):
        payload = {"student_id": "HK888", "name": "李四", "password": "password123"}
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 409

    async def test_wrong_password(self, client):
        r = await client.post(
            "/api/v1/auth/register",
            json={"student_id": "HK777", "name": "王五", "password": "password123"},
        )
        assert r.status_code == 201
        r = await client.post(
            "/api/v1/auth/login",
            json={"student_id": "HK777", "password": "wrong-password"},
        )
        assert r.status_code == 401

    async def test_me_requires_token(self, client):
        assert (await client.get("/api/v1/auth/me")).status_code == 401


# ==========================================================================
# 投票主流程
# ==========================================================================

class TestVotingFlow:
    async def test_vote_then_receipt_then_duplicate(self, client, setup_election):
        s = setup_election
        t = await login(client, s["voters"][0].student_id)

        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [1]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 201, r.text
        code = r.json()["receipt_code"]
        assert code.count("-") == 2

        # 凭证核验：能找到、已计入，且**不含选择信息**
        r = await client.get(f"/api/v1/receipts/{code}")
        body = r.json()
        assert body["found"] is True and body["counted"] is True
        assert "choice" not in body and "candidate" not in body

        # 重复投票被拒
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 409
        assert "重复" in r.json()["detail"]

    async def test_out_of_range_choice_rejected(self, client, setup_election):
        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [99]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 422

    async def test_not_in_roster_rejected(self, client, setup_election):
        s = setup_election
        outsider = await make_user("OUTSIDER")
        t = await login(client, outsider.student_id)
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 403

    async def test_vote_requires_auth(self, client, setup_election):
        s = setup_election
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
        )
        assert r.status_code == 401


# ==========================================================================
# 状态门控与结果
# ==========================================================================

class TestStatusGating:
    async def test_results_hidden_while_open(self, client, setup_election):
        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        r = await client.get(
            f"/api/v1/elections/{s['election_id']}/results",
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 200
        assert r.json()["published"] is False

    async def test_publish_requires_closed(self, client, setup_election):
        s = setup_election
        t = await login(client, s["admin"].student_id)
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/results/publish",
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 409

    async def test_full_lifecycle_to_published(self, client, setup_election):
        s = setup_election
        admin = await login(client, s["admin"].student_id)

        # 3 人投票
        for i, v in enumerate(s["voters"]):
            t = await login(client, v.student_id)
            r = await client.post(
                f"/api/v1/elections/{s['election_id']}/votes",
                json={"position_id": s["position_id"], "choice": [i % 3]},
                headers=auth(t["access_token"]),
            )
            assert r.status_code == 201, r.text

        # open → closed
        r = await client.patch(
            f"/api/v1/elections/{s['election_id']}/status",
            json={"status": "closed"},
            headers=auth(admin["access_token"]),
        )
        assert r.status_code == 200

        # 非法迁移：closed → open
        r = await client.patch(
            f"/api/v1/elections/{s['election_id']}/status",
            json={"status": "open"},
            headers=auth(admin["access_token"]),
        )
        assert r.status_code == 400

        # 计票公示
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/results/publish",
            headers=auth(admin["access_token"]),
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert results and results[0]["ballot_count"] == 3
        assert len(results[0]["digest"]) == 64

        # 公示后不能再投票
        t = await login(client, s["voters"][0].student_id)
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 409


# ==========================================================================
# 权限
# ==========================================================================

class TestPermissions:
    async def test_voter_cannot_change_status(self, client, setup_election):
        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        r = await client.patch(
            f"/api/v1/elections/{s['election_id']}/status",
            json={"status": "closed"},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 403

    async def test_audit_requires_auditor(self, client, setup_election):
        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        assert (await client.get("/api/v1/audit/verify", headers=auth(t["access_token"]))).status_code == 403


# ==========================================================================
# 不变量
# ==========================================================================

class TestInvariants:
    async def test_counts_consistent_after_votes(self, client, setup_election):
        s = setup_election
        for i, v in enumerate(s["voters"]):
            t = await login(client, v.student_id)
            r = await client.post(
                f"/api/v1/elections/{s['election_id']}/votes",
                json={"position_id": s["position_id"], "choice": [i]},
                headers=auth(t["access_token"]),
            )
            assert r.status_code == 201

        async with SessionLocal() as db:
            nb = (await db.execute(select(func.count()).select_from(Ballot))).scalar_one()
            nl = (await db.execute(select(func.count()).select_from(VotesLog))).scalar_one()
            nr = (await db.execute(select(func.count()).select_from(Receipt))).scalar_one()
        assert nb == nl == nr == 3

        admin = await login(client, s["admin"].student_id)
        r = await client.get(
            f"/api/v1/elections/{s['election_id']}/integrity",
            headers=auth(admin["access_token"]),
        )
        assert r.status_code == 200
        assert r.json()["all_passed"] is True

    async def test_ballot_table_has_no_user_id_column(self):
        """结构性匿名性：ballots 表根本不存在 user_id 外键。"""
        cols = {c.name for c in Ballot.__table__.columns}
        assert "user_id" not in cols
        assert "anon_id" in cols

    async def test_voter_roll_has_no_ballot_link(self):
        from app.models import VoterRoll

        cols = {c.name for c in VoterRoll.__table__.columns}
        assert "ballot_id" not in cols


# ==========================================================================
# 并发：一人一票
# ==========================================================================

class TestConcurrency:
    async def test_concurrent_duplicate_votes_only_one_succeeds(self, client, setup_election):
        """
        同一选民并发提交 8 次。断言：
          - 至多 1 次成功（严格相等 1）
          - 数据库里只有 1 张选票、1 条投票记录、1 个凭证
        若 SQLite 因写锁产生失败，那些失败也算"未成功"，不破坏断言。
        """
        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        h = auth(t["access_token"])

        async def attempt(i: int) -> int:
            r = await client.post(
                f"/api/v1/elections/{s['election_id']}/votes",
                json={"position_id": s["position_id"], "choice": [i % 3]},
                headers=h,
            )
            return r.status_code

        codes = await asyncio.gather(*[attempt(i) for i in range(8)])
        successes = sum(1 for c in codes if c == 201)
        assert successes == 1, f"并发下应恰好 1 票成功，实际 {successes}；状态码 {codes}"

        async with SessionLocal() as db:
            assert (await db.execute(select(func.count()).select_from(Ballot))).scalar_one() == 1
            assert (await db.execute(select(func.count()).select_from(VotesLog))).scalar_one() == 1
            assert (await db.execute(select(func.count()).select_from(Receipt))).scalar_one() == 1


# ==========================================================================
# SSE
# ==========================================================================

class TestSSE:
    async def test_stream_headers(self):
        """
        检查 SSE 响应的协议要素：媒体类型、缓存控制、防代理缓冲。

        注意：**不能**用 `client.stream(...)` 去读无限流的 body ——
        httpx 的 ASGITransport 在退出上下文时会等待流结束，导致测试卡死。
        这里直接调用路由函数拿到 StreamingResponse 对象来检查头部。
        """
        from app.api.events import events_turnout

        resp = await events_turnout(election_id=1)
        assert resp.media_type == "text/event-stream"
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        await resp.body_iterator.aclose()

    async def test_stream_emits_open_frame(self):
        """直接消费生成器：首帧必须是 open，证明 SSE 协议格式正确。"""
        from app.api.events import _stream

        gen = _stream("turnout", "turnout", 1)
        try:
            first = await asyncio.wait_for(gen.__anext__(), timeout=3)
        finally:
            await gen.aclose()
        assert "event: open" in first
        assert first.endswith("\n\n")  # SSE 帧必须以空行结束

    async def test_pubsub_delivers_message(self):
        """发布订阅：订阅者能收到发布的消息（内存实现）。"""
        from app.services import pubsub

        pubsub.reset_pubsub()
        bus = pubsub.get_pubsub()
        gen = bus.subscribe("test-channel")

        async def consume():
            return await asyncio.wait_for(gen.__anext__(), timeout=3)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        await bus.publish("test-channel", {"hello": "world"})
        assert await task == {"hello": "world"}
        await gen.aclose()

# ==========================================================================
# 契约一致性（前后端对接约定）
# ==========================================================================

class TestContract:
    async def test_validation_error_detail_is_string(self, client):
        """
        约定：所有错误的 detail 必须是**字符串**。

        FastAPI 默认会把 Pydantic 校验错误返回成数组，
        那会让前端页面上出现 [object Object]。我们在 main.py 里统一压平。
        """
        r = await client.post(
            "/api/v1/auth/register",
            json={"student_id": "x", "password": "1"},
        )
        assert r.status_code == 422
        body = r.json()
        assert isinstance(body["detail"], str), f"detail 应为字符串，实际 {type(body['detail'])}"
        assert "student_id" in body["detail"]

    async def test_business_error_detail_is_string(self, client, setup_election):
        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 409
        assert isinstance(r.json()["detail"], str)

    async def test_turnout_event_uses_snake_case(self, client, setup_election):
        """约定：SSE 推送的字段与 REST 一致，使用 snake_case。"""
        from app.services import pubsub

        pubsub.reset_pubsub()
        bus = pubsub.get_pubsub()
        gen = bus.subscribe(pubsub.CHANNEL_TURNOUT)

        async def consume():
            return await asyncio.wait_for(gen.__anext__(), timeout=5)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)

        s = setup_election
        t = await login(client, s["voters"][0].student_id)
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [1]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 201

        msg = await task
        assert "election_id" in msg
        assert "electionId" not in msg
        await gen.aclose()

    async def test_sse_open_frame_uses_snake_case(self):
        from app.api.events import _stream

        gen = _stream("turnout", "turnout", 1)
        try:
            frame = await asyncio.wait_for(gen.__anext__(), timeout=3)
        finally:
            await gen.aclose()
        assert "election_id" in frame
        assert "electionId" not in frame
