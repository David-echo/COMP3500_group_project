"""Module."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, SessionDep
from ..domain import lifecycle
from ..schemas import ReceiptResponse, VoteRequest, VoteResponse
from ..services import voting
from ..services.voting import VoteError

router = APIRouter(tags=["Voting"])


_STATUS_MAP = {
    "DUPLICATE_VOTE": status.HTTP_409_CONFLICT,
    "ELECTION_NOT_OPEN": status.HTTP_409_CONFLICT,
    "FORBIDDEN": status.HTTP_403_FORBIDDEN,
    "INVALID_CHOICE": 422,
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
}


@router.post(
    "/elections/{election_id}/votes",
    response_model=VoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def cast_vote(
    election_id: int, payload: VoteRequest, session: SessionDep, user: CurrentUser
) -> VoteResponse:
    """Cast vote."""
    try:
        result = await voting.cast_ballot(
            session,
            election_id=election_id,
            position_id=payload.position_id,
            user_id=user.id,
            actor=user.student_id,
            choice=payload.choice,
        )
    except lifecycle.ElectionNotOpen as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except VoteError as exc:
        raise HTTPException(_STATUS_MAP.get(exc.code, 400), exc.message) from exc

    return VoteResponse(
        receipt_code=result.receipt_code,
        cast_at=result.cast_at,
        audit_seq=result.audit_seq,
    )


@router.get("/receipts/{code}", response_model=ReceiptResponse)
async def verify_receipt(code: str, session: SessionDep) -> ReceiptResponse:
    """Verify receipt."""
    data = await voting.verify_receipt(session, code)
    return ReceiptResponse(**data)
