"""Module."""
from __future__ import annotations
import asyncio
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from .db import Base, SessionLocal, engine
from .domain import lifecycle
from .models import Candidate, Election, Position, User, VoterRoll
from .security import hash_password
from .services import voting
ADMIN_ID, ADMIN_PWD = "ADMIN001", "admin12345"
AUDITOR_ID, AUDITOR_PWD = "AUDIT001", "audit12345"
VOTER_PWD = "voter12345"
FIRST_NAMES = ["Ka-ho", "Ho-yin", "Man-yi", "Chun-kit", "Wing-sze", "Tsz-kwan",
               "Yuk-hei", "Ching-man", "Wai-lam", "Hoi-ting", "Sze-ching", "Lok-yan"]
SURNAMES = ["Chan", "Lee", "Wong", "Ho", "Chow", "Cheung", "Lau", "Ng",
            "Choi", "Yeung", "Hui", "Cheng"]
def _vid(i: int) -> str:
    return f"HK{100000 + i:06d}"
async def _get_or_create_user(session, student_id: str, name: str, role: str, pwd: str) -> User:
    user = (
        await session.execute(select(User).where(User.student_id == student_id))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            student_id=student_id,
            name=name,
            password_hash=hash_password(pwd),
            role=role,
        )
        session.add(user)
        await session.flush()
    return user
async def _create_election(
    session, title: str, status: str, method: str,
    opens: datetime | None, closes: datetime | None,
    positions: list[tuple[str, list[tuple[str, str]]]],
) -> Election:
    e = Election(
        title=title,
        description="Demo dataset",
        status=status,
        opens_at=opens,
        closes_at=closes,
        tally_method=method,
    )
    session.add(e)
    await session.flush()
    for ptitle, cands in positions:
        p = Position(election_id=e.id, title=ptitle, seats=1)
        session.add(p)
        await session.flush()
        for idx, (name, party) in enumerate(cands):
            session.add(Candidate(position_id=p.id, idx=idx, name=name, party=party))
    await session.flush()
    await session.refresh(e)
    return e
async def seed() -> dict:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    rng = random.Random(42)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    async with SessionLocal() as s:
        existing = (
            await s.execute(select(func.count()).select_from(Election))
        ).scalar_one()
        if existing:
            return {"seeded": False, "reason": "elections already exist"}
        await _get_or_create_user(s, ADMIN_ID, "Election Administrator", "ADMIN", ADMIN_PWD)
        await _get_or_create_user(s, AUDITOR_ID, "Auditor", "AUDITOR", AUDITOR_PWD)
        voters: list[User] = []
        for i in range(30):
            u = await _get_or_create_user(
                s, _vid(i),
                f"{SURNAMES[i % len(SURNAMES)]} {FIRST_NAMES[(i * 5) % len(FIRST_NAMES)]}",
                "VOTER", VOTER_PWD
            )
            voters.append(u)
        e1 = await _create_election(
            s, "2026 Student Union Chairperson Election", lifecycle.OPEN, "fptp",
            now - timedelta(hours=6), now + timedelta(days=2),
            [("Chairperson", [("Chan Ka-ho", "Student Union"), ("Lee Ho-yin", "Independent"),
                              ("Wong Man-yi", "Student Union"), ("Ho Chun-kit", "Independent"),
                              ("Chow Wing-sze", "Student Union")])],
        )
        await s.commit()
        pid1 = e1.positions[0].id
        for u in voters[:20]:
            s.add(VoterRoll(election_id=e1.id, user_id=u.id, eligible=True))
        for u in voters[20:]:
            s.add(VoterRoll(election_id=e1.id, user_id=u.id, eligible=True))
        await s.commit()
        for u in voters[:20]:
            try:
                await voting.cast_ballot(
                    s, election_id=e1.id, position_id=pid1, user_id=u.id,
                    actor=u.student_id,
                    choice=[rng.choices(range(5), weights=[3, 2, 2, 1, 1])[0]],
                )
            except Exception:
                pass
        e2 = await _create_election(
            s, "2026 Council Student Representative Election", lifecycle.SCHEDULED, "fptp",
            now + timedelta(days=3), now + timedelta(days=10),
            [("Student Representative", [("Ng Wing-yan", "Postgraduate Association"),
                                           ("Cheng Ka-ho", "Undergraduate Association"),
                                           ("Tse Yuen-ling", "Independent")])],
        )
        await s.commit()
        for u in voters:
            s.add(VoterRoll(election_id=e2.id, user_id=u.id, eligible=True))
        await s.commit()
        e3 = await _create_election(
            s, "2026 Environmental Policy Referendum (Ranked Choice)", lifecycle.OPEN, "irv",
            now - timedelta(days=5), now - timedelta(days=1),
            [("Preferred Option", [("Option A: Full recycling", "Green Group"),
                                                ("Option B: District pilot", "Administration"),
                                                ("Option C: Defer review", "Finance")])],
        )
        await s.commit()
        pid3 = e3.positions[0].id
        for u in voters:
            s.add(VoterRoll(election_id=e3.id, user_id=u.id, eligible=True))
        await s.commit()
        for u in voters[:26]:
            order = [0, 1, 2]
            rng.shuffle(order)
            try:
                await voting.cast_ballot(
                    s, election_id=e3.id, position_id=pid3, user_id=u.id,
                    actor=u.student_id, choice=order[: rng.randint(2, 3)],
                )
            except Exception:
                pass
        from .api.elections import tick_elections
        await tick_elections(s)
        e4 = await _create_election(
            s, "2025 Library Opening Hours Referendum", lifecycle.OPEN, "fptp",
            now - timedelta(days=30), now - timedelta(days=20),
            [("Extended Opening Hours", [("Extend to 23:00", "Proposal side"),
                                                      ("Keep 21:00", "Opposition side")])],
        )
        await s.commit()
        pid4 = e4.positions[0].id
        for u in voters:
            s.add(VoterRoll(election_id=e4.id, user_id=u.id, eligible=True))
        await s.commit()
        for u in voters[:24]:
            try:
                await voting.cast_ballot(
                    s, election_id=e4.id, position_id=pid4, user_id=u.id,
                    actor=u.student_id, choice=[rng.choices([0, 1], weights=[3, 2])[0]],
                )
            except Exception:
                pass
        from .services import results as results_svc
        await tick_elections(s)
        await results_svc.publish(s, e4.id, actor=ADMIN_ID)
    return {"seeded": True, "elections": 4, "voters": 30}
if __name__ == "__main__":
    print(asyncio.run(seed()))
