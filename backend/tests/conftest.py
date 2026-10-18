"""pytest 配置与公共 fixture。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 让 `import app.xxx` 可用
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 必须在导入 app 之前设置环境变量（config 有 lru_cache）
# 注意：字段名是 database_url，所以环境变量必须是 DATABASE_URL（不是 ELECTION_DB）
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["REDIS_URL"] = ""  # 使用内存发布订阅

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    Ballot,
    Candidate,
    Election,
    Position,
    Receipt,
    Result,
    User,
    VoterRoll,
    VotesLog,
)
from app.security import hash_password  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """每个测试都从空库开始（保证互不干扰）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as s:
        for model in (AuditLog, Result, Receipt, VotesLog, Ballot, VoterRoll,
                      Candidate, Position, Election, User):
            await s.execute(delete(model))
        await s.commit()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------
# 造数助手
# --------------------------------------------------------------------------

async def make_user(student_id: str, role: str = "VOTER", pwd: str = "pass12345") -> User:
    async with SessionLocal() as s:
        u = User(
            student_id=student_id,
            name=student_id,
            password_hash=hash_password(pwd),
            role=role,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def login(client: AsyncClient, student_id: str, pwd: str = "pass12345") -> dict:
    r = await client.post(
        "/api/v1/auth/login", json={"student_id": student_id, "password": pwd}
    )
    assert r.status_code == 200, r.text
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def setup_election():
    """
    构造：1 名管理员 + 3 名选民 + 1 场进行中的选举（3 名候选）。
    返回各 ID 与 token。
    """
    admin = await make_user("ADMIN1", "ADMIN")
    voters = [await make_user(f"V{i:03d}") for i in range(3)]

    async with SessionLocal() as s:
        e = Election(title="测试选举", status="open", tally_method="fptp")
        s.add(e)
        await s.flush()
        p = Position(election_id=e.id, title="主席", seats=1)
        s.add(p)
        await s.flush()
        for idx, name in enumerate(["甲", "乙", "丙"]):
            s.add(Candidate(position_id=p.id, idx=idx, name=name, party=""))
        for v in voters:
            s.add(VoterRoll(election_id=e.id, user_id=v.id, eligible=True))
        await s.commit()
        return {
            "admin": admin,
            "voters": voters,
            "election_id": e.id,
            "position_id": p.id,
        }
