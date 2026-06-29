"""
게임 라우터: 역할/아바타 셋업, 맵/월드, NPC 스폰, 진행도, 전적.

중요: NPC 의 role(사기꾼/정상, 구매자 유형)과 tactics(수법/행동)는 '정답지'다.
이 라우터는 그 정답지를 절대 클라이언트로 내려보내지 않는다.
(클라이언트 JS 를 뜯어봐도 누가 사기꾼/빌런인지 알 수 없어야 게임이 성립한다.)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.database import db_dependency
from app.deps import get_current_user
from app.models import (
    LocationRequest,
    RoleSetupRequest,
    RoleSwitchRequest,
    UpdateAvatarRequest,
)
from app import geoip
from app import spawns as spawn_mgr
from app import worldgen

router = APIRouter(prefix="/api/game", tags=["game"])

# 판매자 모드 기본 카테고리 화이트리스트 (검증/표시는 프론트와 공유)
SELLER_CATEGORIES = {
    "electronics", "camping", "beauty", "home", "fashion", "books", "general",
}

DEFAULT_AVATAR = {
    "skin": "light",
    "hat": "none",
    "shirt": "terracotta",
    "pants": "denim",
    "accessory": "none",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _avatar_of(user: sqlite3.Row) -> dict:
    """user row 의 avatar_json 을 파싱. 없거나 깨졌으면 기본 아바타."""
    raw = user["avatar_json"] if "avatar_json" in user.keys() else None
    if not raw:
        return dict(DEFAULT_AVATAR)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            merged = dict(DEFAULT_AVATAR)
            merged.update({k: str(v) for k, v in data.items() if k in DEFAULT_AVATAR})
            return merged
    except (json.JSONDecodeError, TypeError):
        pass
    return dict(DEFAULT_AVATAR)


def _coins(user: sqlite3.Row) -> int:
    return user["coins"] if ("coins" in user.keys() and user["coins"] is not None) else 0


def _item_count(user: sqlite3.Row) -> int:
    raw = user["inventory_json"] if "inventory_json" in user.keys() else None
    if not raw:
        return 0
    try:
        data = json.loads(raw)
        return len(data) if isinstance(data, list) else 0
    except (json.JSONDecodeError, TypeError):
        return 0


def _setup_state(user: sqlite3.Row) -> dict:
    return {
        "setup_completed": bool(user["setup_completed"]),
        "game_role": user["game_role"],
        "seller_category": user["seller_category"],
        "avatar": _avatar_of(user),
    }


# ============================================================
#  역할 / 아바타 셋업
# ============================================================
@router.get("/setup")
def get_setup(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """현재 셋업 상태. 프론트는 setup_completed=false 면 셋업 화면을 띄운다."""
    return _setup_state(user)


@router.post("/setup")
def save_setup(
    body: RoleSetupRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """역할 + 아바타 + (판매자면) 카테고리 저장 → 셋업 완료 처리."""
    seller_category = None
    if body.game_role == "seller":
        cat = (body.seller_category or "general").lower()
        seller_category = cat if cat in SELLER_CATEGORIES else "general"

    avatar = body.avatar.model_dump()
    conn.execute(
        "UPDATE users SET game_role = ?, avatar_json = ?, seller_category = ?, "
        "setup_completed = 1, updated_at = ? WHERE id = ?",
        (body.game_role, json.dumps(avatar, ensure_ascii=False),
         seller_category, _now(), user["id"]),
    )
    # 역할이 바뀌면 기존 스폰은 의미가 없으니 비운다 (다음 world/spawns 호출에서 새로 채워짐)
    conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
    conn.commit()

    fresh = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return _setup_state(fresh)


@router.post("/role")
def switch_role(
    body: RoleSwitchRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """게임 중 역할(구매자/판매자) 전환. 아바타는 유지, 스폰은 새 역할에 맞게 다시 채운다."""
    role = body.game_role
    # 판매자로 바꾸는데 카테고리가 없으면 기본값을 준다. 구매자면 기존 카테고리 보존.
    new_cat = (user["seller_category"] or "electronics") if role == "seller" else user["seller_category"]
    conn.execute(
        "UPDATE users SET game_role = ?, seller_category = ?, setup_completed = 1, updated_at = ? WHERE id = ?",
        (role, new_cat, _now(), user["id"]),
    )
    # 역할이 바뀌면 등장 NPC 종류가 달라지므로 기존 스폰을 비운다 (다음 world 에서 새로 채움).
    conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
    conn.commit()
    return {"game_role": role, "seller_category": new_cat}


@router.post("/avatar")
def update_avatar(
    body: UpdateAvatarRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """아바타만 갱신 (역할/카테고리는 유지)."""
    avatar = body.avatar.model_dump()
    conn.execute(
        "UPDATE users SET avatar_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(avatar, ensure_ascii=False), _now(), user["id"]),
    )
    conn.commit()
    return {"avatar": avatar}


# ============================================================
#  위치 (대략값만 저장 → 맵 시드)
# ============================================================
@router.post("/location")
def set_location(
    body: LocationRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """
    브라우저 지오로케이션의 '대략' 좌표를 받아 맵 시드로 쓴다.
    정밀 좌표는 저장하지 않으려고 소수 2자리(약 1km)로 반올림한다.
    위치를 안 줘도(거부해도) 사용자 고유 시드로 맵이 생성된다.
    """
    lat = round(body.lat, 2) if body.lat is not None else None
    lng = round(body.lng, 2) if body.lng is not None else None
    # 좌표 → 대략 도시/구 이름 (무키 역지오코딩, 실패해도 진행). 동네 이름 표시용.
    geo = geoip.reverse_geocode(lat, lng)
    place_label = geo["place_label"] if geo else None
    profile = worldgen.build_and_store_profile(
        conn, user, lat=lat, lng=lng,
        place_label=place_label, requested_provider=body.provider,
    )
    # 맵이 새로 생기면 기존 스폰 좌표는 무효 → 비우고 다음 호출에서 새 맵 위에 채운다
    conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
    conn.commit()
    return {
        "provider": profile["provider"],
        "seed": profile["seed"],
        "place_label": place_label,
        "town_name": profile["map"].get("town_name"),
        "regenerated": True,
    }


def _client_public_ip(request: Request) -> str | None:
    """역방향 프록시 헤더(X-Forwarded-For) 또는 직접 연결에서 공인 IP 를 고른다."""
    xff = request.headers.get("x-forwarded-for")
    peer = request.client.host if request.client else None
    return geoip.public_client_ip(xff, peer)


def _maybe_ip_locate(
    conn: sqlite3.Connection, user: sqlite3.Row, profile: dict, request: Request
) -> dict:
    """
    아직 위치 기반이 아닌(좌표 없음) 맵이면, 접속 IP 로 대략 위치를 한 번 추정해
    그 지역 시드/이름으로 맵을 다시 만든다. 실패하면 표식만 남기고 그대로 둔다.
    (게임 입장 때만 호출되므로 빈도가 낮고, 실패해도 게임은 절차적 맵으로 진행.)
    """
    if profile.get("lat") is not None or profile["map"].get("geo_attempted"):
        return profile

    geo = geoip.geolocate_ip(_client_public_ip(request))
    if geo and geo.get("lat") is not None:
        lat = round(float(geo["lat"]), 2)
        lng = round(float(geo["lng"]), 2)
        # IP 는 보통 도시 수준(예: "서울")까지만 준다. 좌표를 한 번 더 역지오코딩해
        # 구/동 수준(예: "강남구")으로 더 자세한 동네 이름을 얻는다.
        place_label = geo.get("place_label")
        fine = geoip.reverse_geocode(lat, lng)
        if fine and fine.get("place_label"):
            place_label = fine["place_label"]
        profile = worldgen.build_and_store_profile(
            conn, user, lat=lat, lng=lng, place_label=place_label
        )
        # 맵(=벤더 스폿)이 바뀌었으니 기존 스폰 좌표는 무효 → 비우고 새 맵 위에서 채운다.
        conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
        return profile
    # 추정 실패: 다음 입장마다 외부 호출을 반복하지 않도록 표식만 남긴다.
    return worldgen.mark_geo_attempted(conn, user, profile)


# ============================================================
#  월드 (맵 + 플레이어 + 스폰)
# ============================================================
@router.get("/world")
def get_world(
    request: Request,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """
    맵 프로필 + 플레이어(아바타/역할) + 현재 활성 스폰 + 진행도.
    역할에 따라 등장하는 NPC 종류가 달라진다:
      - buyer 모드  → 판매자 NPC (사기꾼/정상)
      - seller 모드 → 구매자 NPC (정상/빌런 등)
    좌표가 아직 없으면 접속 IP 로 대략 위치를 한 번 추정해 동네를 그 지역에 맞춘다.
    """
    game_role = user["game_role"] or "buyer"
    profile = worldgen.get_or_build_profile(conn, user)
    # 갓 만든/재생성한 맵 쓰기를 먼저 커밋한다 → 위치추정 네트워크 호출(최대 수 초) 동안
    # DB 쓰기 잠금을 붙들고 있지 않게 해서 동시 요청의 쓰기와 충돌하지 않도록.
    conn.commit()
    profile = _maybe_ip_locate(conn, user, profile, request)
    spawns = spawn_mgr.refresh_and_list(conn, user, profile)
    conn.commit()

    return {
        "player": {
            "display_name": user["display_name"],
            "level": user["level"],
            "xp": user["xp"],
            "trust_score": user["trust_score"],
            "game_role": game_role,
            "seller_category": user["seller_category"],
            "avatar": _avatar_of(user),
            "coins": _coins(user),
            "items": _item_count(user),
        },
        "map": profile["map"],
        "spawns": spawns,
    }


@router.get("/spawns")
def get_spawns(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 활성 스폰 목록 + 만료된 건 정리하고 부족하면 새로 채운다."""
    profile = worldgen.get_or_build_profile(conn, user)
    spawns = spawn_mgr.refresh_and_list(conn, user, profile)
    conn.commit()
    return {"spawns": spawns}


@router.post("/spawns/refresh")
def refresh_spawns(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """디버그/개발용: 스폰을 강제로 싹 비우고 새로 채운다."""
    profile = worldgen.get_or_build_profile(conn, user)
    spawns = spawn_mgr.force_refresh(conn, user, profile)
    conn.commit()
    return {"spawns": spawns}


# ============================================================
#  진행도 / 전적 / 리더보드
# ============================================================
@router.get("/profile")
def get_profile(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """전적실: 누적 통계 + 최근 거래 기록."""
    results = conn.execute(
        """
        SELECT tr.verdict, tr.correct, tr.score, tr.coaching, tr.created_at,
               tr.game_role, n.name AS npc_name, n.item_name
        FROM trade_results tr
        JOIN npcs n ON n.id = tr.npc_id
        WHERE tr.user_id = ?
        ORDER BY tr.created_at DESC
        LIMIT 20
        """,
        (user["id"],),
    ).fetchall()

    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    # 구매자 모드에서 사기 당한 횟수 (전적 카드용)
    scammed = sum(1 for r in results if r["verdict"] == "scammed")

    return {
        "player": {
            "display_name": user["display_name"],
            "level": user["level"],
            "xp": user["xp"],
            "trust_score": user["trust_score"],
            "game_role": user["game_role"] or "buyer",
            "coins": _coins(user),
            "items": _item_count(user),
        },
        "stats": {
            "total_trades": total,
            "correct": correct,
            "scammed": scammed,
            "accuracy": round(100 * correct / total) if total else 0,
        },
        "history": [dict(r) for r in results],
    }


@router.get("/leaderboard")
def get_leaderboard(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """간단한 명예의 전당 — XP 순 상위 10명."""
    rows = conn.execute(
        "SELECT display_name, level, xp, trust_score FROM users ORDER BY xp DESC, trust_score DESC LIMIT 10"
    ).fetchall()
    return {"leaderboard": [dict(r) for r in rows]}
