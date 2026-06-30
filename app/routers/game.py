"""
게임 라우터: 역할/아바타 셋업, 맵/월드, NPC 스폰, 진행도, 전적.

중요: NPC 의 role(사기꾼/정상, 구매자 유형)과 tactics(수법/행동)는 '정답지'다.
이 라우터는 그 정답지를 절대 클라이언트로 내려보내지 않는다.
(클라이언트 JS 를 뜯어봐도 누가 사기꾼/빌런인지 알 수 없어야 게임이 성립한다.)
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.ai import adaptive_debug, adaptive_repository, adaptive_selector
from app.ai import pattern_taxonomy as taxonomy
from app.config import get_settings
from app.database import db_dependency
from app.deps import get_current_user
from app.models import (
    BuyerPreferenceRequest,
    EquipRequest,
    LocationRequest,
    RoleSetupRequest,
    RoleSwitchRequest,
    SellerListingRequest,
    UnequipRequest,
    UpdateAvatarRequest,
)
from app import geoip
from app import preferences as prefs_mgr
from app import rewards as rewards_mgr
from app import spawns as spawn_mgr
from app import worldgen
from app.market import catalog

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


def _setup_payload(conn: sqlite3.Connection, user: sqlite3.Row) -> dict:
    """셋업 상태 + 마켓 선호/판매글 (프론트 셋업 화면 프리필용)."""
    state = _setup_state(user)
    state["preferences"] = prefs_mgr.get_preferences(conn, user["id"])
    return state


# ============================================================
#  역할 / 아바타 셋업
# ============================================================
@router.get("/setup")
def get_setup(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 셋업 상태. 프론트는 setup_completed=false 면 셋업 화면을 띄운다."""
    return _setup_payload(conn, user)


@router.post("/setup")
def save_setup(
    body: RoleSetupRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """역할 + 아바타 + (판매자면) 카테고리 저장 → 셋업 완료 처리."""
    seller_category = None
    if body.game_role == "seller":
        # 새 15종 카테고리든 옛 부스 카테고리든 표준 부스 카테고리로 환원한다.
        cat = catalog.canonical_of((body.seller_category or "general").lower())
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
    return _setup_payload(conn, fresh)


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
#  마켓 선호 / 판매글 / 카탈로그
# ============================================================
@router.get("/catalog")
def get_catalog(_: sqlite3.Row = Depends(get_current_user)) -> dict:
    """셋업/판매글 UI 가 쓰는 카탈로그 메타데이터 (카테고리/상태/증거/상품 자동완성)."""
    return catalog.catalog_meta()


@router.get("/preferences")
def get_preferences(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """구매 위시리스트 + 판매글."""
    return prefs_mgr.get_preferences(conn, user["id"])


@router.post("/preferences")
def save_preferences(
    body: BuyerPreferenceRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """구매자 위시리스트 저장. 등장 매물 카테고리가 바뀌므로 스폰을 비운다."""
    saved = prefs_mgr.save_buyer_preferences(
        conn, user["id"], body.buyer_category,
        body.buyer_price_preference, body.buyer_trade_preference,
    )
    conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
    conn.commit()
    return saved


@router.get("/listing")
def get_listing(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """판매자 모드: 내 판매글."""
    return {"seller_listing": prefs_mgr.get_seller_listing(conn, user["id"])}


@router.post("/listing")
def save_listing(
    body: SellerListingRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """판매글 저장(위생처리). 구매자 NPC 가 이 물건을 보고 반응하도록 스폰을 비운다."""
    listing = prefs_mgr.normalize_seller_listing(body)
    saved = prefs_mgr.save_seller_listing(conn, user["id"], listing)
    conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
    conn.commit()
    return {"seller_listing": saved}


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

    # 장착된 코스튬을 아바타에 입히고, 장착된 도구 효과를 함께 내려준다.
    avatar = _avatar_of(user)
    overrides = rewards_mgr.equipped_cosmetic_overrides(conn, user["id"])
    if overrides:
        avatar = {**avatar, **overrides}
    effects = sorted(rewards_mgr.equipped_effects(conn, user["id"]))

    # HUD 표시용 마켓 요약: 구매자 모드는 '찾는 물건(카테고리)', 판매자 모드는 '내 판매글'.
    prefs = prefs_mgr.get_preferences(conn, user["id"])
    buyer_cat = prefs.get("buyer_category") or "random"
    seller_listing = prefs.get("seller_listing") or None
    market_hud = {
        "buyer_category": buyer_cat,
        "buyer_category_label": catalog.CATEGORY_LABEL.get(buyer_cat, "전체"),
        "seller_listing_title": (
            (seller_listing.get("product_name") if seller_listing else None) or None
        ),
        "seller_category_label": (
            seller_listing.get("category_label") if seller_listing else None
        ),
    }

    return {
        "player": {
            "display_name": user["display_name"],
            "level": user["level"],
            "xp": user["xp"],
            "trust_score": user["trust_score"],
            "game_role": game_role,
            "seller_category": user["seller_category"],
            "avatar": avatar,
            "coins": _coins(user),
            "items": _item_count(user),
            "equipped_effects": effects,
            "market": market_hud,
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
               tr.game_role,
               COALESCE(tr.counterparty_name, n.name)     AS npc_name,
               COALESCE(tr.item_name, n.item_name)        AS item_name
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


# ============================================================
#  인벤토리 (거래 가방) / 장착
# ============================================================
def _inventory_payload(conn: sqlite3.Connection, user: sqlite3.Row) -> dict:
    inv = rewards_mgr.list_inventory(conn, user["id"])
    inv["effects"] = sorted(rewards_mgr.equipped_effects(conn, user["id"]))
    inv["cosmetic_overrides"] = rewards_mgr.equipped_cosmetic_overrides(conn, user["id"])
    return inv


@router.get("/inventory")
def get_inventory(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """거래 가방: 보유 아이템 + 장착 상태 + 장착 효과."""
    return _inventory_payload(conn, user)


@router.post("/equip")
def equip(
    body: EquipRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    try:
        rewards_mgr.equip_item(conn, user["id"], body.item_id, body.slot)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    conn.commit()
    return _inventory_payload(conn, user)


@router.post("/unequip")
def unequip(
    body: UnequipRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    rewards_mgr.unequip_slot(conn, user["id"], body.slot)
    conn.commit()
    return _inventory_payload(conn, user)


# ============================================================
#  거래 습관 리포트 (기존 거래 기록만 사용 — 적응형 메모리는 아직 미구현)
# ============================================================
def _parse_flags(raw) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _build_habit_report(rows: list[dict]) -> dict:
    total = len(rows)
    buyer = [r for r in rows if (r.get("game_role") or "buyer") == "buyer"]
    seller = [r for r in rows if r.get("game_role") == "seller"]

    def acc(group):
        return round(100 * sum(1 for r in group if r["correct"]) / len(group)) if group else 0

    buyer_acc, seller_acc = acc(buyer), acc(seller)
    avg_score = round(sum(r["score"] for r in rows) / total) if total else 0
    verdicts = Counter(r["verdict"] for r in rows)
    missed = Counter(f for r in rows for f in _parse_flags(r.get("missed_flags_json")))
    detected = Counter(f for r in rows for f in _parse_flags(r.get("detected_flags_json")))

    strengths, weaknesses, recs = [], [], []

    if buyer:
        if buyer_acc >= 70:
            strengths.append("구매할 때 사기 판매자를 잘 가려내요.")
        scammed = verdicts.get("scammed", 0)
        if scammed:
            weaknesses.append(f"사기를 당한 적이 {scammed}회 있어요. 선입금·외부 링크 신호에 더 민감해지면 좋아요.")
            recs.append("구매자 모드에서 '초저가 미끼 → 선입금 → 외부 링크' 패턴을 의식하며 연습해 보세요.")
        if verdicts.get("missed_deal", 0):
            weaknesses.append("멀쩡한 판매자를 과하게 의심해 정상 거래를 놓친 적이 있어요. '행동'을 기준으로 보세요.")
    if seller:
        if seller_acc >= 70:
            strengths.append("판매할 때 진상·위험 구매자에 침착하게 대응해요.")
        if verdicts.get("over_refunded", 0):
            weaknesses.append("부당한 환불 요구에 휘둘린 적이 있어요.")
            recs.append("판매자 모드에서 '고지·기록으로 정중히 거절 → 플랫폼 분쟁' 흐름을 연습해 보세요.")
        if verdicts.get("unsafe_response", 0):
            weaknesses.append("감정적·위험한 대응으로 점수를 잃은 적이 있어요. 사실·기록·절차로만 대응하는 연습이 필요해요.")
        if verdicts.get("missed_legitimate_claim", 0):
            weaknesses.append("정당한 하자 주장을 거절해 신뢰를 잃은 적이 있어요. 합리적 해결을 연습해 보세요.")

    if not strengths:
        strengths.append("거래 경험을 차곡차곡 쌓고 있어요." if total else "아직 거래 기록이 없어요. 첫 거래를 해보세요!")
    if not weaknesses and total:
        weaknesses.append("뚜렷한 약점은 안 보여요. 더 어려운 상대에 도전해 보세요.")
    if not recs:
        if not seller:
            recs.append("판매자 모드도 플레이해 환불 빌런·막깎이 대응을 익혀 보세요.")
        elif not buyer:
            recs.append("구매자 모드도 플레이해 사기 판매자 구분을 익혀 보세요.")
        elif buyer_acc < seller_acc:
            recs.append("구매자 모드 정확도가 낮은 편이에요. 사기 신호 포착을 반복 훈련해 보세요.")
        else:
            recs.append("판매자 모드 정확도가 낮은 편이에요. 침착한 분쟁 대응을 반복 훈련해 보세요.")

    return {
        "summary": {
            "total_trades": total,
            "buyer_trades": len(buyer),
            "seller_trades": len(seller),
            "buyer_accuracy": buyer_acc,
            "seller_accuracy": seller_acc,
            "avg_score": avg_score,
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recs,
        "common_missed_flags": [f for f, _ in missed.most_common(5)],
        "common_correct": [f for f, _ in detected.most_common(5)],
    }


@router.get("/habit-report")
def habit_report(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """내 거래 습관 요약 (강점/약점/추천). 기존 trade_results 만 사용한다."""
    rows = conn.execute(
        "SELECT game_role, verdict, correct, score, detected_flags_json, missed_flags_json "
        "FROM trade_results WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
        (user["id"],),
    ).fetchall()
    return _build_habit_report([dict(r) for r in rows])


# ============================================================
#  적응형 훈련 리포트 (적응형 메모리 기반 — 사용자 안전 노출만)
# ============================================================
def _recommend_next_training(prof: dict) -> str:
    """약점 패턴의 안전한 대응을 다음 훈련 추천으로 (라벨/대응만, 내부 키 비노출)."""
    weak = prof.get("weak_patterns") or []
    if weak:
        wk = min(weak, key=lambda pk: prof["mastery_by_pattern"][pk]["mastery"])
        card = taxonomy.public_pattern_card(wk)
        if card:
            return f"‘{card['label']}’ 대응을 더 연습해 보세요. {card['safe_counter']}"
    if prof.get("history_count", 0) == 0:
        return "아직 훈련 기록이 없어요. 마을에서 첫 거래를 시작해 보세요!"
    if prof.get("untrained_patterns"):
        return "아직 마주치지 못한 위험 신호가 있어요. 다양한 상대와 거래해 보며 폭을 넓혀 보세요."
    return "주요 위험 신호를 잘 다루고 있어요. 더 어려운 상대에 도전해 보세요."


def _empty_role_profile() -> dict:
    return {
        "strengths": [], "weaknesses": [],
        "recommended_next_training": "아직 훈련 데이터가 없어요.",
        "recommended_difficulty": "same", "history_count": 0, "mastery_cards": [],
    }


def _training_profile_for_role(conn: sqlite3.Connection, user_id: int, role: str) -> dict:
    """한 모드의 사용자 안전 리포트 (강점/약점/추천/숙련도 카드). 실패 시 빈 리포트로 안전 강등."""
    try:
        return _build_role_profile(conn, user_id, role)
    except Exception:
        return _empty_role_profile()


def _build_role_profile(conn: sqlite3.Connection, user_id: int, role: str) -> dict:
    prof = adaptive_selector.get_user_training_profile(conn, user_id, role)
    cards = []
    for c in prof["mastery_by_pattern"].values():
        if c["times_seen"] <= 0:
            continue
        pct = c["mastery_pct"]
        status = "강함" if pct >= 80 else ("약함" if pct < 40 else "보통")
        cards.append({
            "label": c["label"],
            "family": c["pattern_family"],
            "mastery_pct": pct,
            "times_seen": c["times_seen"],
            "status": status,
        })
    cards.sort(key=lambda x: x["mastery_pct"], reverse=True)
    strengths = [c["label"] for c in cards if c["mastery_pct"] >= 80]
    weaknesses = [c["label"] for c in cards if c["mastery_pct"] < 40]
    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_next_training": _recommend_next_training(prof),
        "recommended_difficulty": prof["recommended_difficulty"],
        "history_count": prof["history_count"],
        "mastery_cards": cards,
    }


@router.get("/training-profile")
def training_profile(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """실력 분석 / 훈련 리포트 — 구매자·판매자 모드별 강점/약점/추천.

    사용자 안전 정보만 내려보낸다. 숨은 패턴 키·선택 로직은 노출하지 않는다.
    """
    settings = get_settings()
    payload = {
        "adaptive_enabled": settings.adaptive_scenarios_enabled,
        "buyer": _training_profile_for_role(conn, user["id"], "buyer"),
        "seller": _training_profile_for_role(conn, user["id"], "seller"),
    }
    # 디버그 설명은 ADAPTIVE_DEBUG_EXPLAIN=true 일 때만 (기본 false → 절대 노출 안 함)
    if adaptive_debug.is_enabled():
        try:
            payload["_debug"] = {
                "buyer": adaptive_debug.explain_user(conn, user["id"], "buyer"),
                "seller": adaptive_debug.explain_user(conn, user["id"], "seller"),
            }
        except Exception:
            pass
    return payload


@router.post("/training-profile/reset")
def reset_training_profile(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 로그인 사용자의 적응형 훈련 메모리만 초기화한다 (데모/연습용).

    계정·거래 기록·인벤토리는 건드리지 않는다. 전역 삭제 기능은 제공하지 않는다.
    """
    try:
        counts = adaptive_repository.reset_user_adaptive(conn, user["id"])
        conn.commit()
    except Exception:
        return {"reset": False, "deleted": {},
                "message": "적응형 메모리 초기화 중 문제가 생겼어요. (계정·거래 기록은 그대로입니다)"}
    return {
        "reset": True,
        "deleted": counts,
        "message": "적응형 훈련 메모리를 초기화했어요. (계정·거래 기록은 그대로 유지됩니다)",
    }


@router.get("/rewards/catalog")
def rewards_catalog(_: sqlite3.Row = Depends(get_current_user)) -> dict:
    """전체 아이템 도감 (공개 정보)."""
    return {
        "items": [
            {
                "id": it["id"], "name": it["name"], "item_type": it["item_type"],
                "rarity": it["rarity"], "slot": it["slot"],
                "description": it["description"], "effect_key": it["effect_key"],
                "visual": it["visual"],
            }
            for it in rewards_mgr.ITEM_DEFS
        ]
    }
