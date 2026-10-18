"""结果接口 (Results router) —— 成员 4 负责"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..deps import AdminUser, SessionDep
from ..schemas import ResultOut, ResultsResponse
from ..services import results as results_svc
from ..services.voting import VoteError

router = APIRouter(tags=["结果"])


@router.get("/elections/{election_id}/results", response_model=ResultsResponse)
async def get_results(election_id: int, session: SessionDep) -> ResultsResponse:
    """未截止不公开；已截止返回结果（必要时先计票）。"""
    try:
        data = await results_svc.get_results(session, election_id)
    except VoteError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from exc

    if not data["published"]:
        return ResultsResponse(
            published=False,
            election_id=election_id,
            status=data["status"],
            message=data["message"],
            results=[],
        )
    return ResultsResponse(
        published=True,
        election_id=election_id,
        status=data["status"],
        message="",
        results=[ResultOut(**r) for r in data["results"]],
    )


@router.post("/elections/{election_id}/results/publish", response_model=ResultsResponse)
async def publish_results(election_id: int, session: SessionDep, admin: AdminUser) -> ResultsResponse:
    """计票并公示（仅 ADMIN，且选举须为 closed）。"""
    try:
        await results_svc.publish(session, election_id, actor=admin.student_id)
    except VoteError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc

    data = await results_svc.get_results(session, election_id)
    return ResultsResponse(
        published=True,
        election_id=election_id,
        status=data["status"],
        results=[ResultOut(**r) for r in data["results"]],
    )
