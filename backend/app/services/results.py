"""Module."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ..domain import lifecycle, tally
from ..models import (
    Ballot,
    Candidate,
    Election,
    Position,
    Receipt,
    Result,
    VoterRoll,
    VotesLog,
)
from ..security import decrypt_choice
from . import audit, pubsub
from .voting import VoteError
async def compute_tally(session: AsyncSession, position_id: int) -> dict:
    """Compute tally."""
    position = (
        await session.execute(select(Position).where(Position.id == position_id))
    ).scalar_one_or_none()
    if position is None:
        raise VoteError("NOT_FOUND", "Position not found")
    election = (
        await session.execute(select(Election).where(Election.id == position.election_id))
    ).scalar_one()
    if election.status not in (lifecycle.CLOSED, lifecycle.PUBLISHED):
        raise VoteError("ELECTION_NOT_CLOSED", "The election has not closed yet; counting is not allowed")
    candidates = (
        await session.execute(
            select(Candidate)
            .where(Candidate.position_id == position_id)
            .order_by(Candidate.idx)
        )
    ).scalars().all()
    ballots = (
        await session.execute(
            select(Ballot)
            .where(Ballot.position_id == position_id, Ballot.counted.is_(True))
            .order_by(Ballot.id)
        )
    ).scalars().all()
    choices: list[list[int]] = []
    ballot_ids: list[int] = []
    for b in ballots:
        try:
            choices.append(decrypt_choice(b.choice_enc))
            ballot_ids.append(b.id)
        except Exception:
            await audit.append(
                session,
                op="tally.ballot_rejected",
                actor="system",
                payload={"ballot_id": b.id, "position_id": position_id, "reason": "ciphertext verification failed"},
            )
    strategy = tally.get_strategy(election.tally_method)
    result = strategy.tally(choices, len(candidates))
    digest = tally.tally_digest(strategy.name, result.counts, ballot_ids)
    return {
        "position_id": position_id,
        "position_title": position.title,
        "tally_method": strategy.name,
        "tally_label": strategy.label,
        "ballot_count": len(ballot_ids),
        "counts": {str(k): v for k, v in result.counts.items()},
        "winner_idx": result.winner,
        "winner_name": next(
            (c.name for c in candidates if c.idx == result.winner), None
        ),
        "digest": digest,
        "note": result.note,
        "rounds": result.rounds,
    }
async def publish(session: AsyncSession, election_id: int, actor: str) -> dict:
    """Publish."""
    election = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if election is None:
        raise VoteError("NOT_FOUND", "Election not found")
    if election.status == lifecycle.PUBLISHED:
        rows = (
            await session.execute(
                select(Result).where(Result.election_id == election_id)
            )
        ).scalars().all()
        return {
            "published": True,
            "already": True,
            "results": [json.loads(r.counts_json) | {"digest": r.digest} for r in rows],
            "full": [_result_dict(r) for r in rows],
        }
    if election.status == lifecycle.CLOSED:
        lifecycle.assert_transition(lifecycle.CLOSED, lifecycle.PUBLISHED)
    else:
        raise VoteError("ELECTION_NOT_CLOSED", "The election has not closed yet; results cannot be published")
    positions = (
        await session.execute(select(Position).where(Position.election_id == election_id))
    ).scalars().all()
    computed = []
    for p in positions:
        res = await compute_tally(session, p.id)
        existing = (
            await session.execute(select(Result).where(Result.position_id == p.id))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Result(
                    election_id=election_id,
                    position_id=p.id,
                    tally_method=res["tally_method"],
                    counts_json=json.dumps(res["counts"]),
                    winner_idx=res["winner_idx"],
                    rounds_json=json.dumps(res["rounds"], ensure_ascii=False),
                    digest=res["digest"],
                    ballot_count=res["ballot_count"],
                    published_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
        computed.append(res)
    election.status = lifecycle.PUBLISHED
    await audit.append(
        session,
        op="results.published",
        actor=actor,
        payload={
            "election_id": election_id,
            "positions": [
                {"position_id": r["position_id"], "ballot_count": r["ballot_count"],
                 "digest": r["digest"]}
                for r in computed
            ],
        },
    )
    await session.commit()
    await pubsub.get_pubsub().publish(
        pubsub.CHANNEL_RESULTS,
        {
            "election_id": election_id,
            "status": lifecycle.PUBLISHED,
            "results": [
                {"position_id": r["position_id"], "counts": r["counts"],
                 "winner_idx": r["winner_idx"], "digest": r["digest"]}
                for r in computed
            ],
        },
    )
    return {"published": True, "already": False, "full": computed}
def _result_dict(r: Result) -> dict:
    return {
        "position_id": r.position_id,
        "tally_method": r.tally_method,
        "counts": json.loads(r.counts_json),
        "winner_idx": r.winner_idx,
        "digest": r.digest,
        "ballot_count": r.ballot_count,
        "rounds": json.loads(r.rounds_json),
    }
async def get_results(session: AsyncSession, election_id: int) -> dict:
    """Get results."""
    election = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if election is None:
        raise VoteError("NOT_FOUND", "Election not found")
    if election.status in (lifecycle.SCHEDULED, lifecycle.OPEN):
        return {
            "published": False,
            "election_id": election_id,
            "status": election.status,
            "message": "The election is still open; results stay hidden until it closes",
            "results": [],
        }
    rows = (
        await session.execute(select(Result).where(Result.election_id == election_id))
    ).scalars().all()
    by_pos = {r.position_id: r for r in rows}
    positions = (
        await session.execute(select(Position).where(Position.election_id == election_id))
    ).scalars().all()
    out = []
    for p in positions:
        r = by_pos.get(p.id)
        if r is None:
            continue
        out.append(
            {
                "position_id": p.id,
                "position_title": p.title,
                "tally_method": r.tally_method,
                "tally_label": tally.get_strategy(r.tally_method).label,
                "ballot_count": r.ballot_count,
                "counts": json.loads(r.counts_json),
                "winner_idx": r.winner_idx,
                "winner_name": next(
                    (
                        c.name
                        for c in (
                            await session.execute(
                                select(Candidate).where(Candidate.position_id == p.id)
                            )
                        ).scalars().all()
                        if c.idx == r.winner_idx
                    ),
                    None,
                ),
                "digest": r.digest,
                "note": "",
                "rounds": json.loads(r.rounds_json),
            }
        )
    return {
        "published": True,
        "election_id": election_id,
        "status": election.status,
        "message": "",
        "results": out,
    }
# ==========================================================================
# ==========================================================================
async def check_integrity(session: AsyncSession, election_id: int) -> dict:
    checks = []
    dup = (
        await session.execute(
            select(VotesLog.position_id, VotesLog.user_id, func.count().label("c"))
            .group_by(VotesLog.position_id, VotesLog.user_id)
            .having(func.count() > 1)
        )
    ).all()
    checks.append(
        {
            "name": "No duplicate vote records",
            "passed": len(dup) == 0,
            "detail": "No voter has voted twice for the same position" if not dup else f"{len(dup)} duplicate group(s) found",
        }
    )
    voted = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election_id, VoterRoll.has_voted.is_(True)
            )
        )
    ).scalar_one()
    logged = (
        await session.execute(
            select(func.count())
            .select_from(VotesLog)
            .join(Position, Position.id == VotesLog.position_id)
            .where(Position.election_id == election_id)
        )
    ).scalar_one()
    checks.append(
        {
            "name": "Voters marked as voted == vote records",
            "passed": voted == logged,
            "detail": f"{voted} on roll / {logged} records",
        }
    )
    positions = (
        await session.execute(select(Position).where(Position.election_id == election_id))
    ).scalars().all()
    detail = []
    ok = True
    for p in positions:
        nb = (
            await session.execute(
                select(func.count()).select_from(Ballot).where(Ballot.position_id == p.id)
            )
        ).scalar_one()
        nl = (
            await session.execute(
                select(func.count()).select_from(VotesLog).where(VotesLog.position_id == p.id)
            )
        ).scalar_one()
        nr = (
            await session.execute(
                select(func.count()).select_from(Receipt).where(Receipt.position_id == p.id)
            )
        ).scalar_one()
        consistent = nb == nl == nr
        ok = ok and consistent
        detail.append(f"{p.title}: ballots {nb} / records {nl} / receipts {nr}")
    checks.append(
        {
            "name": "Ballots == vote records == receipts",
            "passed": ok,
            "detail": "; ".join(detail) if detail else "No positions",
        }
    )
    return {
        "election_id": election_id,
        "all_passed": all(c["passed"] for c in checks),
        "checks": checks,
    }
