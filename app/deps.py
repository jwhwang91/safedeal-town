"""
공통 의존성 (FastAPI Depends).
요청 헤더의 Bearer 토큰을 까서 '지금 로그인한 유저'를 꺼내준다.
보호된 API 들은 이 get_current_user 를 Depends 로 받기만 하면 된다.
"""
from __future__ import annotations

import sqlite3

from fastapi import Depends, Header, HTTPException, status

from app.database import db_dependency
from app.security import decode_access_token


def get_current_user(
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> sqlite3.Row:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 만료되었거나 올바르지 않습니다. 다시 로그인해 주세요.",
        )
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (int(payload["sub"]),)
    ).fetchone()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="계정을 찾을 수 없습니다.",
        )
    return user
