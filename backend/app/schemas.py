"""
Pydantic 模型 (API schemas)
===========================

对应课程 Lecture 4「需求可验证性」的工程化体现：
接口的**输入输出结构**在此集中声明，FastAPI 会自动生成 OpenAPI 文档，
前端可直接据此对接（与 docs/API 契约一一对应）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["VOTER", "ADMIN", "AUDITOR"]
Status = Literal["scheduled", "open", "closed", "published"]
TallyMethod = Literal["fptp", "irv"]


# ==========================================================================
# 通用
# ==========================================================================

class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorBody


# ==========================================================================
# 认证
# ==========================================================================

class RegisterRequest(BaseModel):
    student_id: str = Field(min_length=4, max_length=32, examples=["HK12345678"])
    name: str = Field(default="", max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    student_id: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: str
    name: str
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ==========================================================================
# 选举
# ==========================================================================

class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    idx: int
    name: str
    party: str


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    seats: int
    candidates: list[CandidateOut] = []


class Turnout(BaseModel):
    voted: int
    total: int
    percent: float


class ElectionOut(BaseModel):
    id: int
    title: str
    description: str
    status: Status
    status_label: str
    opens_at: datetime | None
    closes_at: datetime | None
    tally_method: TallyMethod
    positions: list[PositionOut]
    turnout: Turnout
    my_vote_status: Literal["NOT_VOTED", "VOTED", "NOT_ELIGIBLE"] = "NOT_ELIGIBLE"


class CandidateIn(BaseModel):
    idx: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=120)
    party: str = Field(default="", max_length=120)


class PositionIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    seats: int = Field(default=1, ge=1)
    candidates: list[CandidateIn] = []


class ElectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    tally_method: TallyMethod = "fptp"
    positions: list[PositionIn] = []


class StatusChange(BaseModel):
    status: Status


# ==========================================================================
# 投票
# ==========================================================================

class VoteRequest(BaseModel):
    position_id: int
    choice: list[int] = Field(min_length=1, description="候选序号；排序制为偏好顺序")


class VoteResponse(BaseModel):
    receipt_code: str
    cast_at: datetime
    audit_seq: int


class ReceiptResponse(BaseModel):
    found: bool
    message: str
    election_title: str | None = None
    counted: bool | None = None
    cast_at: datetime | None = None


# ==========================================================================
# 结果
# ==========================================================================

class ResultOut(BaseModel):
    position_id: int
    position_title: str
    tally_method: str
    tally_label: str
    ballot_count: int
    counts: dict[str, int]
    winner_idx: int | None
    winner_name: str | None
    digest: str
    note: str = ""
    rounds: list[dict[str, Any]] = []


class ResultsResponse(BaseModel):
    published: bool
    election_id: int
    status: Status
    message: str = ""
    results: list[ResultOut] = []


# ==========================================================================
# 审计与完整性
# ==========================================================================

class AuditEntryOut(BaseModel):
    seq: int
    op: str
    actor: str
    payload: dict[str, Any]
    ts: str
    hash: str


class AuditVerifyOut(BaseModel):
    ok: bool
    length: int
    first_bad_seq: int | None
    message: str
    chain_tip: str


class InvariantCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class IntegrityOut(BaseModel):
    election_id: int
    all_passed: bool
    checks: list[InvariantCheck]
