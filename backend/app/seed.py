"""
种子数据 (Seed)
==============

生成可直接演示的数据集：
  - 1 个管理员、1 个审计员、若干选民
  - 4 场覆盖全部状态的选举（进行中 / 未开始 / 已截止 / 已公布）
  - 进行中与已截止的选举预投部分选票（走真实 service，因此审计链真实）

用法:
    python -m app.seed          # 幂等：已存在则跳过
"""

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

SURNAMES = "陈李黄何周张刘吴蔡杨许郑谢郭洪曾朱罗梁宋"


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
        description="演示数据",
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
            return {"seeded": False, "reason": "数据库中已有选举数据"}

        await _get_or_create_user(s, ADMIN_ID, "选举管理员", "ADMIN", ADMIN_PWD)
        await _get_or_create_user(s, AUDITOR_ID, "审计员", "AUDITOR", AUDITOR_PWD)

        # ---------- 选民（30 人） ----------
        voters: list[User] = []
        for i in range(30):
            u = await _get_or_create_user(
                s, _vid(i), SURNAMES[i % len(SURNAMES)] + "同学", "VOTER", VOTER_PWD
            )
            voters.append(u)

        # ---------- ① 进行中的选举 ----------
        e1 = await _create_election(
            s, "2026 学生事务委员会主席选举", lifecycle.OPEN, "fptp",
            now - timedelta(hours=6), now + timedelta(days=2),
            [("主席", [("陈嘉禾", "学生会"), ("李浩然", "独立"),
                      ("黄敏怡", "学生会"), ("何俊杰", "独立"), ("周咏诗", "学生会")])],
        )
        await s.commit()

        # 预投 20 票，保留 10 名未投票选民便于演示
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

        # ---------- ② 未开始的选举 ----------
        # 必须录入选民册，否则开票后无人可投（会显示 0/0 投票率）
        e2 = await _create_election(
            s, "2026 校董会学生代表选举", lifecycle.SCHEDULED, "fptp",
            now + timedelta(days=3), now + timedelta(days=10),
            [("学生代表", [("吴卓颖", "研究生会"), ("郑家豪", "本科生会"), ("谢婉玲", "独立")])],
        )
        await s.commit()
        for u in voters:
            s.add(VoterRoll(election_id=e2.id, user_id=u.id, eligible=True))
        await s.commit()

        # ---------- ③ 已截止、待计票（IRV） ----------
        e3 = await _create_election(
            s, "2026 环保政策咨询公投（排序复选）", lifecycle.OPEN, "irv",
            now - timedelta(days=5), now - timedelta(days=1),
            [("首选方案", [("方案甲：全面回收", "环保组"), ("方案乙：分区试点", "行政组"),
                          ("方案丙：押后检讨", "财务组")])],
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

        # 让时间窗口自动把它推到 closed
        from .api.elections import tick_elections

        await tick_elections(s)

        # ---------- ④ 已公布的选举 ----------
        # 注意：状态机拒绝"对 closed 选举投票"，所以必须先建成 open，
        # 预投完成后由 tick_elections() 依据 closes_at 自动推到 closed。
        e4 = await _create_election(
            s, "2025 图书馆开放时间公投", lifecycle.OPEN, "fptp",
            now - timedelta(days=30), now - timedelta(days=20),
            [("延长开放时间", [("同意延长至 23:00", "提案方"), ("维持 21:00", "反对方")])],
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

        # 依据时间窗口把 e4 推到 closed，然后计票公示
        await tick_elections(s)
        await results_svc.publish(s, e4.id, actor=ADMIN_ID)

    return {"seeded": True, "elections": 4, "voters": 30}


if __name__ == "__main__":
    print(asyncio.run(seed()))
