"""
인증 라우터: 회원가입 / 로그인 / 내 정보.

보안 포인트:
 - 비밀번호는 scrypt 해시로만 저장 (security.py)
 - 로그인 5회 연속 실패 시 10분 잠금
 - 로그인 성공 시 JWT 토큰 발급, 이후 요청은 이 토큰으로 인증
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import db_dependency
from app.deps import get_current_user
from app.models import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_MAX_FAILED = 5
_LOCK_MINUTES = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/register", response_model=TokenResponse)
def register(
    body: RegisterRequest,
    conn: sqlite3.Connection = Depends(db_dependency),
) -> TokenResponse:
    exists = conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 아이디입니다.",
        )

    password_hash, password_salt = hash_password(body.password)
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO users
            (username, display_name, email, password_hash, password_salt,
             level, xp, trust_score, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, 0, 50, ?, ?)
        """,
        (body.username, body.display_name, body.email,
         password_hash, password_salt, now, now),
    )
    conn.commit()
    user_id = cur.lastrowid
    token = create_access_token(user_id, body.username)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    conn: sqlite3.Connection = Depends(db_dependency),
) -> TokenResponse:
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    if not user:
        # 아이디 존재 여부를 노출하지 않도록 동일한 메시지
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    # 잠금 확인
    if user["locked_until"]:
        locked_until = datetime.fromisoformat(user["locked_until"])
        if locked_until > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="로그인 시도가 많아 잠시 잠겼습니다. 잠시 후 다시 시도해 주세요.",
            )

    if not verify_password(body.password, user["password_hash"], user["password_salt"]):
        failed = user["failed_login_attempts"] + 1
        locked_until = None
        if failed >= _MAX_FAILED:
            locked_until = (
                datetime.now(timezone.utc) + timedelta(minutes=_LOCK_MINUTES)
            ).isoformat()
            failed = 0
        conn.execute(
            "UPDATE users SET failed_login_attempts = ?, locked_until = ?, updated_at = ? WHERE id = ?",
            (failed, locked_until, _now(), user["id"]),
        )
        conn.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    # 성공: 실패 카운트 초기화
    conn.execute(
        "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = ?, updated_at = ? WHERE id = ?",
        (_now(), _now(), user["id"]),
    )
    conn.commit()
    token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserProfile)
def me(user: sqlite3.Row = Depends(get_current_user)) -> UserProfile:
    return UserProfile(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        level=user["level"],
        xp=user["xp"],
        trust_score=user["trust_score"],
        game_role=user["game_role"],
        setup_completed=bool(user["setup_completed"]),
    )
