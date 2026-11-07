"""Module."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ..domain import lifecycle
from ..models import (
    Ballot,
    Candidate,
    Election,
    Position,
    Receipt,
    VoterRoll,
    VotesLog,
)
from ..security import encrypt_choice, new_anon_id, new_receipt_code
from . import audit, pubsub
class VoteError(Exception):
    """VoteError."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
class CastResult:
    def __init__(self, receipt_code: str, cast_at: datetime, audit_seq: int) -> None:
        self.receipt_code = receipt_code
        self.cast_at = cast_at
        self.audit_seq = audit_seq
async def cast_ballot(
    session: AsyncSession,
    *,
    election_id: int,
    position_id: int,
    user_id: int,
    actor: str,
    choice: list[int],
) -> CastResult:
    if not choice:
        raise VoteError("INVALID_CHOICE", "Select at least one candidate")
    election = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if election is None:
        raise VoteError("NOT_FOUND", "Election not found")
    lifecycle.assert_accepts_ballots(election.status)
    position = (
        await session.execute(
            select(Position).where(
                Position.id == position_id, Position.election_id == election_id
            )
        )
    ).scalar_one_or_none()
    if position is None:
        raise VoteError("NOT_FOUND", "Position not found in this election")
    num_candidates = (
        await session.execute(
            select(func.count()).select_from(Candidate).where(
                Candidate.position_id == position_id
            )
        )
    ).scalar_one()
    roll = (
        await session.execute(
            select(VoterRoll).where(
                VoterRoll.election_id == election_id, VoterRoll.user_id == user_id
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if roll is None:
        raise VoteError("FORBIDDEN", "You are not on the voter roll for this election")
    if not roll.eligible:
        raise VoteError("FORBIDDEN", "Your voting eligibility has been revoked")
    norm: list[int] = []
    for c in choice:
        if not isinstance(c, int) or not (0 <= c < num_candidates):
            raise VoteError("INVALID_CHOICE", f"Candidate index {c} is out of range (this position has {num_candidates} candidates)")
        if c not in norm:
            norm.append(c)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    anon_id = new_anon_id()
    try:
        ballot = Ballot(
            election_id=election_id,
            position_id=position_id,
            anon_id=anon_id,
            choice_enc=encrypt_choice(norm),
            cast_at=now,
            counted=True,
        )
        session.add(ballot)
        await session.flush()
        session.add(
            VotesLog(
                position_id=position_id,
                user_id=user_id,
                ballot_id=ballot.id,
                created_at=now,
            )
        )
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise VoteError("DUPLICATE_VOTE", "You have already voted and cannot vote again") from exc
    receipt = Receipt(
        election_id=election_id,
        position_id=position_id,
        ballot_id=ballot.id,
        code=new_receipt_code(),
        anon_id=anon_id,
        created_at=now,
    )
    session.add(receipt)
    # Only mark the roll complete after every position has a ballot.
    n_positions = (
        await session.execute(
            select(func.count()).select_from(Position).where(
                Position.election_id == election_id
            )
        )
    ).scalar_one()
    n_cast = (
        await session.execute(
            select(func.count())
            .select_from(VotesLog)
            .join(Position, Position.id == VotesLog.position_id)
            .where(
                Position.election_id == election_id,
                VotesLog.user_id == user_id,
            )
        )
    ).scalar_one()
    roll.has_voted = n_cast == n_positions
    roll.voted_at = now if roll.has_voted else None
    seq = await audit.append(
        session,
        op="ballot.cast",
        actor=actor,
        payload={
            "election_id": election_id,
            "position_id": position_id,
            "user_id": user_id,
            "receipt_code": receipt.code,
            "ballot_id": ballot.id,
        },
        ts=now.isoformat(),
    )
    await session.commit()
    await _publish_turnout(session, election_id)
    return CastResult(receipt.code, now, seq)
async def _publish_turnout(session: AsyncSession, election_id: int) -> None:
    """Publish turnout."""
    total = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election_id
            )
        )
    ).scalar_one()
    voted = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election_id, VoterRoll.has_voted.is_(True)
            )
        )
    ).scalar_one()
    await pubsub.get_pubsub().publish(
        pubsub.CHANNEL_TURNOUT,
        {
            "election_id": election_id,
            "voted": voted,
            "total": total,
            "percent": round(voted * 100.0 / total, 1) if total else 0.0,
        },
    )
async def verify_receipt(session: AsyncSession, code: str) -> dict:
    """Verify receipt."""
    code = code.strip().upper()
    row = (
        await session.execute(
            select(Receipt, Ballot, Election)
            .join(Ballot, Ballot.id == Receipt.ballot_id)
            .join(Election, Election.id == Receipt.election_id)
            .where(Receipt.code == code)
        )
    ).first()
    if row is None:
        return {"found": False, "message": "Receipt code not found. Please check the code and try again."}
    receipt, ballot, election = row
    if receipt.verified_at is None:
        receipt.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()
    return {
        "found": True,
        "message": "This ballot was counted and has not been modified since" if ballot.counted else "This ballot was not counted",
        "election_title": election.title,
        "counted": bool(ballot.counted),
        "cast_at": ballot.cast_at,
    }
