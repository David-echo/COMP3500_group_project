"""选举接口 (Elections router) —— 成员 4 负责"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from ..deps import AdminUser, CurrentUser, SessionDep
from ..domain import lifecycle
from ..models import Candidate, Election, Position, Result, VoterRoll
from ..schemas import (
    ElectionCreate,
    ElectionOut,
    PositionOut,
    StatusChange,
    Turnout,
)

router = APIRouter(prefix="/elections", tags=["选举"])


async def _build_out(session, election: Election, user: User | None) -> ElectionOut:  # noqa: F821
    positions = []
    for p in sorted(election.positions, key=lambda x: x.id):
        cands = sorted(p.candidates, key=lambda c: c.idx)
        positions.append(
            PositionOut(
                id=p.id,
                title=p.title,
                seats=p.seats,
                candidates=[
                    {"id": c.id, "idx": c.idx, "name": c.name, "party": c.party}
                    for c in cands
                ],
            )
        )

    total = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election.id
            )
        )
    ).scalar_one()
    voted = (
        await session.execute(
            select(func.count()).select_from(VoterRoll).where(
                VoterRoll.election_id == election.id,
                VoterRoll.has_voted.is_(True),
            )
        )
    ).scalar_one()

    my = "NOT_ELIGIBLE"
    if user is not None:
        roll = (
            await session.execute(
                select(VoterRoll).where(
                    VoterRoll.election_id == election.id, VoterRoll.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if roll is not None:
            my = "VOTED" if roll.has_voted else "NOT_VOTED"

    return ElectionOut(
        id=election.id,
        title=election.title,
        description=election.description,
        status=election.status,
        status_label=lifecycle.LABELS.get(election.status, election.status),
        opens_at=election.opens_at,
        closes_at=election.closes_at,
        tally_method=election.tally_method,
        positions=positions,
        turnout=Turnout(
            voted=voted,
            total=total,
            percent=round(voted * 100.0 / total, 1) if total else 0.0,
        ),
        my_vote_status=my,
    )


async def tick_elections(session) -> list[dict]:
    """按时间自动推进状态（scheduled→open→closed）。写审计。"""
    from ..services import audit

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    changed = []
    rows = (await session.execute(select(Election))).scalars().all()
    for e in rows:
        target = None
        if e.status == lifecycle.SCHEDULED and e.opens_at and now >= e.opens_at:
            target = lifecycle.OPEN
        elif e.status == lifecycle.OPEN and e.closes_at and now >= e.closes_at:
            target = lifecycle.CLOSED
        if target:
            lifecycle.assert_transition(e.status, target)
            old = e.status
            e.status = target
            await audit.append(
                session,
                op="election.status",
                actor="system",
                payload={"election_id": e.id, "from": old, "to": target,
                         "reason": "时间窗口自动推进"},
            )
            changed.append({"election_id": e.id, "from": old, "to": target})
    if changed:
        await session.commit()
    return changed


@router.get("", response_model=list[ElectionOut])
async def list_elections(session: SessionDep, user: CurrentUser) -> list[ElectionOut]:
    """返回当前用户可见的选举（选民只返回名册内的）。"""
    await tick_elections(session)
    rows = (await session.execute(select(Election).order_by(Election.id))).scalars().all()

    if user.role in ("ADMIN", "AUDITOR"):
        return [await _build_out(session, e, user) for e in rows]

    my_elections = set(
        (
            await session.execute(
                select(VoterRoll.election_id).where(VoterRoll.user_id == user.id)
            )
        ).scalars().all()
    )
    return [await _build_out(session, e, user) for e in rows if e.id in my_elections]


@router.get("/{election_id}", response_model=ElectionOut)
async def get_election(election_id: int, session: SessionDep, user: CurrentUser) -> ElectionOut:
    e = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "选举不存在")
    return await _build_out(session, e, user)


@router.post("", response_model=ElectionOut, status_code=status.HTTP_201_CREATED)
async def create_election(
    payload: ElectionCreate, session: SessionDep, admin: AdminUser
) -> ElectionOut:
    e = Election(
        title=payload.title,
        description=payload.description,
        status=lifecycle.SCHEDULED,
        opens_at=payload.opens_at,
        closes_at=payload.closes_at,
        tally_method=payload.tally_method,
    )
    session.add(e)
    await session.flush()

    for pin in payload.positions:
        p = Position(election_id=e.id, title=pin.title, seats=pin.seats)
        session.add(p)
        await session.flush()
        for c in pin.candidates:
            session.add(
                Candidate(position_id=p.id, idx=c.idx, name=c.name, party=c.party)
            )

    await session.commit()
    await session.refresh(e)
    return await _build_out(session, e, admin)


@router.patch("/{election_id}/status", response_model=ElectionOut)
async def change_status(
    election_id: int, payload: StatusChange, session: SessionDep, admin: AdminUser
) -> ElectionOut:
    """状态变更唯一入口：非法迁移一律拒绝（对应 FR-9）。"""
    from ..services import audit

    e = (
        await session.execute(select(Election).where(Election.id == election_id))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "选举不存在")

    try:
        lifecycle.assert_transition(e.status, payload.status)
    except lifecycle.InvalidTransition as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    old = e.status
    e.status = payload.status
    await audit.append(
        session,
        op="election.status",
        actor=admin.student_id,
        payload={"election_id": e.id, "from": old, "to": payload.status,
                 "reason": "管理员操作"},
    )
    await session.commit()
    return await _build_out(session, e, admin)


@router.get("/{election_id}/integrity")
async def integrity(election_id: int, session: SessionDep, auditor: AdminUser):
    from ..services.results import check_integrity

    return await check_integrity(session, election_id)
