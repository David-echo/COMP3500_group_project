"""Module."""
from __future__ import annotations
import asyncio
import pytest
from sqlalchemy import func, select
from app.db import SessionLocal
from app.models import Ballot, Candidate, Position, Receipt, VoterRoll, VotesLog
from .conftest import auth, login, make_user
# ==========================================================================
# ==========================================================================
class TestAuth:
    async def test_register_and_login(self, client):
        r = await client.post(
            "/api/v1/auth/register",
            json={"student_id": "HK999", "name": "Zhang San", "password": "password123"},
        )
        assert r.status_code == 201, r.text
        r = await client.post(
            "/api/v1/auth/login",
            json={"student_id": "HK999", "password": "password123"},
        )
        assert r.status_code == 200
        assert r.json()["user"]["student_id"] == "HK999"
    async def test_duplicate_student_id_rejected(self, client):
        payload = {"student_id": "HK888", "name": "Li Si", "password": "password123"}
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 409
    async def test_wrong_password(self, client):
        r = await client.post(
            "/api/v1/auth/register",
            json={"student_id": "HK777", "name": "Wang Wu", "password": "password123"},
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
# ==========================================================================
class TestVotingFlow:
    async def test_multi_position_resume_completion_and_integrity(self, client, setup_election):
        s = setup_election
        async with SessionLocal() as db:
            second = Position(election_id=s["election_id"], title="Secretary", seats=1)
            db.add(second)
            await db.flush()
            db.add(Candidate(position_id=second.id, idx=0, name="Dana", party=""))
            await db.commit()
        base = f"/api/v1/elections/{s['election_id']}"
        voter = auth((await login(client, s["voters"][0].student_id))["access_token"])
        other = auth((await login(client, s["voters"][1].student_id))["access_token"])
        admin = auth((await login(client, s["admin"].student_id))["access_token"])

        # Vote out of order, then refetch exactly as a refreshed ballot page does.
        r = await client.post(
            f"{base}/votes", json={"position_id": second.id, "choice": [0]}, headers=voter,
        )
        assert r.status_code == 201, r.text
        refreshed = (await client.get("/api/v1/elections", headers=voter)).json()[0]
        assert refreshed["voted_position_ids"] == [second.id]
        assert refreshed["my_vote_status"] == "NOT_VOTED"
        assert refreshed["turnout"]["voted"] == 0
        assert (await client.get(base, headers=other)).json()["voted_position_ids"] == []
        assert (await client.get(f"{base}/integrity", headers=admin)).json()["all_passed"]
        async with SessionLocal() as db:
            roll = (await db.execute(select(VoterRoll).where(
                VoterRoll.election_id == s["election_id"],
                VoterRoll.user_id == s["voters"][0].id,
            ))).scalar_one()
            assert roll.has_voted is False and roll.voted_at is None
            # An old partial-completion flag must not prevent resuming.
            roll.has_voted = True
            await db.commit()
        assert (await client.get(base, headers=voter)).json()["my_vote_status"] == "NOT_VOTED"
        assert not (await client.get(f"{base}/integrity", headers=admin)).json()["all_passed"]

        r = await client.post(
            f"{base}/votes", json={"position_id": s["position_id"], "choice": [1]}, headers=voter,
        )
        assert r.status_code == 201, r.text
        refreshed = (await client.get("/api/v1/elections", headers=voter)).json()[0]
        assert set(refreshed["voted_position_ids"]) == {s["position_id"], second.id}
        assert refreshed["my_vote_status"] == "VOTED"
        assert refreshed["turnout"]["voted"] == 1
        async with SessionLocal() as db:
            roll = (await db.execute(select(VoterRoll).where(
                VoterRoll.election_id == s["election_id"],
                VoterRoll.user_id == s["voters"][0].id,
            ))).scalar_one()
            assert roll.has_voted is True and roll.voted_at is not None
        duplicate = await client.post(
            f"{base}/votes", json={"position_id": second.id, "choice": [0]}, headers=voter,
        )
        assert duplicate.status_code == 409
        # One completed voter plus one partial voter still passes integrity.
        r = await client.post(
            f"{base}/votes", json={"position_id": s["position_id"], "choice": [0]}, headers=other,
        )
        assert r.status_code == 201, r.text
        check = await client.get(f"{base}/integrity", headers=admin)
        assert check.status_code == 200
        assert check.json()["all_passed"], check.text

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
        r = await client.get(f"/api/v1/receipts/{code}")
        body = r.json()
        assert body["found"] is True and body["counted"] is True
        assert "choice" not in body and "candidate" not in body
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 409
        assert "already voted" in r.json()["detail"]
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
        r = await client.patch(
            f"/api/v1/elections/{s['election_id']}/status",
            json={"status": "open"},
            headers=auth(admin["access_token"]),
        )
        assert r.status_code == 400
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/results/publish",
            headers=auth(admin["access_token"]),
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        assert results and results[0]["ballot_count"] == 3
        assert len(results[0]["digest"]) == 64
        t = await login(client, s["voters"][0].student_id)
        r = await client.post(
            f"/api/v1/elections/{s['election_id']}/votes",
            json={"position_id": s["position_id"], "choice": [0]},
            headers=auth(t["access_token"]),
        )
        assert r.status_code == 409
# ==========================================================================
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
        """Test ballot table has no user id column."""
        cols = {c.name for c in Ballot.__table__.columns}
        assert "user_id" not in cols
        assert "anon_id" in cols
    async def test_voter_roll_has_no_ballot_link(self):
        from app.models import VoterRoll
        cols = {c.name for c in VoterRoll.__table__.columns}
        assert "ballot_id" not in cols
# ==========================================================================
# ==========================================================================
class TestConcurrency:
    async def test_concurrent_duplicate_votes_only_one_succeeds(self, client, setup_election):
        """Test concurrent duplicate votes only one succeeds."""
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
        assert successes == 1, f"exactly one vote should succeed under concurrency, got {successes}; status codes {codes}"
        async with SessionLocal() as db:
            assert (await db.execute(select(func.count()).select_from(Ballot))).scalar_one() == 1
            assert (await db.execute(select(func.count()).select_from(VotesLog))).scalar_one() == 1
            assert (await db.execute(select(func.count()).select_from(Receipt))).scalar_one() == 1
# ==========================================================================
# SSE
# ==========================================================================
class TestSSE:
    async def test_stream_headers(self):
        """Test stream headers."""
        from app.api.events import events_turnout
        resp = await events_turnout(election_id=1)
        assert resp.media_type == "text/event-stream"
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        await resp.body_iterator.aclose()
    async def test_stream_emits_open_frame(self):
        """Test stream emits open frame."""
        from app.api.events import _stream
        gen = _stream("turnout", "turnout", 1)
        try:
            first = await asyncio.wait_for(gen.__anext__(), timeout=3)
        finally:
            await gen.aclose()
        assert "event: open" in first
        assert first.endswith("\n\n")
    async def test_pubsub_delivers_message(self):
        """Test pubsub delivers message."""
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
# ==========================================================================
class TestContract:
    async def test_validation_error_detail_is_string(self, client):
        """Test validation error detail is string."""
        r = await client.post(
            "/api/v1/auth/register",
            json={"student_id": "x", "password": "1"},
        )
        assert r.status_code == 422
        body = r.json()
        assert isinstance(body["detail"], str), f"detail should be a string, got {type(body['detail'])}"
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
        """Test turnout event uses snake case."""
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
