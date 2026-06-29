"""
보안 유틸: 비밀번호 해시 + 로그인 토큰(JWT).

- 비밀번호는 평문으로 저장하지 않는다.
  scrypt 해시 + 회원별 salt + 앱 전역 pepper 를 섞어서 저장한다.
- 로그인하면 JWT 토큰을 발급한다. 클라이언트는 이후 요청마다
  Authorization: Bearer <토큰> 헤더로 자기 신분을 증명한다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings

_ALGO = "HS256"


# ---------- 비밀번호 ----------

def hash_password(plain: str) -> tuple[str, str]:
    """평문 비밀번호 -> (해시, salt). 둘 다 hex 문자열."""
    pepper = get_settings().password_pepper
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        (plain + pepper).encode("utf-8"),
        salt=salt,
        n=2**14, r=8, p=1,
        dklen=32,
    )
    return digest.hex(), salt.hex()


def verify_password(plain: str, password_hash: str, password_salt: str) -> bool:
    """입력한 비밀번호가 저장된 해시와 맞는지 확인 (타이밍 공격 방지 비교)."""
    pepper = get_settings().password_pepper
    try:
        salt = bytes.fromhex(password_salt)
    except ValueError:
        return False
    digest = hashlib.scrypt(
        (plain + pepper).encode("utf-8"),
        salt=salt,
        n=2**14, r=8, p=1,
        dklen=32,
    )
    return hmac.compare_digest(digest.hex(), password_hash)


# ---------- 토큰 ----------

def create_access_token(user_id: int, username: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def decode_access_token(token: str) -> dict | None:
    """토큰을 풀어서 payload 를 돌려준다. 만료/위조면 None."""
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[_ALGO])
    except JWTError:
        return None
