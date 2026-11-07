"""Module."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..deps import CurrentUser, SessionDep
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: SessionDep) -> UserOut:
    """Register."""
    user = User(
        student_id=payload.student_id.strip().upper(),
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role="VOTER",
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This student ID is already registered") from None
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    user = (
        await session.execute(
            select(User).where(User.student_id == payload.student_id.strip().upper())
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect student ID or password")
    token = create_access_token(user.student_id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
