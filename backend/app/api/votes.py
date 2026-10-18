"""投票与凭证接口 (Votes & receipts) —— 成员 4 负责"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, SessionDep
from ..domain import lifecycle
from ..schemas import ReceiptResponse, VoteRequest, VoteResponse
from ..services import voting
from ..services.voting import VoteError

router = APIRouter(tags=["投票"])


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
    """
    投出一票。

    校验顺序固定（与 API 契约一致）：
      登录 → 名册 → 选举状态 → 候选合法 → 唯一约束仲裁
    """
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
    """
    凭证核验（无需登录）。

    ⚠️ 响应中**不包含**选择内容，防止凭证被用于证明投票选择（防贿选/胁迫）。
    """
    data = await voting.verify_receipt(session, code)
    return ReceiptResponse(**data)
