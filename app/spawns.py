"""
NPC 스폰 매니저 (백엔드 관리).

마을의 NPC 는 고정 배치가 아니라 '나타났다 사라졌다' 한다.
  - 역할에 맞는 NPC 풀에서 랜덤으로 골라
  - 맵의 보행 가능한 벤더 스폿에
  - 랜덤 수명(expires_at)을 갖고 등장한다.
  - 수명이 다하면 사라지고, 부족분은 다시 채워진다 → 자연스러운 순환.

정답지(role/tactics)는 절대 내려보내지 않는다. 공개 필드만 직렬화한다.
"""
from __future__ import annotations

import json
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

# 동시에 보이는 NPC 수. 동네가 넓어졌으니 더 많이 띄운다.
# (NPC 풀보다 크면 같은 인물이 다른 자리에 한두 번 더 등장할 수 있다 — 의도된 폴백.)
_TARGET_ACTIVE = 8
_LIFETIME_MIN = 60
_LIFETIME_MAX = 150

# 구매자 NPC 의 외형 테마는 '역할과 무관하게' 스폰별로 정한다.
# (역할이 그대로 테마/이름/ID 로 새어나가면 게임의 핵심인 '정체 추리'가 깨진다.)
_BUYER_DISPLAY_THEMES = ["buyer_friendly", "buyer_casual", "buyer_pushy", "buyer_shifty"]


def _buyer_theme_for(spawn_id: str) -> str:
    """spawn_instance_id 로 결정적이지만 역할과 무관한 외형을 고른다."""
    h = sum(ord(c) for c in spawn_id)
    return _BUYER_DISPLAY_THEMES[h % len(_BUYER_DISPLAY_THEMES)]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _eligible_kind(game_role: str) -> str:
    """buyer 모드 → 판매자 NPC, seller 모드 → 구매자 NPC."""
    return "buyer" if game_role == "seller" else "seller"


def _allowed_difficulties(level: int) -> set[str]:
    """레벨이 오를수록 더 어려운(정교한) 사기꾼/빌런이 등장한다."""
    if level >= 3:
        return {"easy", "medium", "hard"}
    return {"easy", "medium"}  # 1~2레벨: 아직 고난도(hard)는 등장하지 않음


def _public_spawn(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> dict | None:
    """active_spawns + npcs 조인해 공개 가능한 필드만 추린다."""
    npc = conn.execute(
        "SELECT id, name, item_name, item_category, listing_price, sprite_color, "
        "npc_kind, visual_theme, category FROM npcs WHERE id = ?",
        (row["npc_id"],),
    ).fetchone()
    if not npc:
        return None
    remaining = max(0, int((_parse(row["expires_at"]) - now).total_seconds()))

    # 정답지 보호:
    #  - npc_id 는 절대 내려보내지 않는다 (슬러그가 role/tactic 을 그대로 노출함).
    #    클라이언트는 spawn_instance_id 만 들고 다니고, 대화 시작 때 서버가 매핑한다.
    #  - 구매자 외형 테마는 역할과 무관하게 스폰별로 정한다.
    #  - 판매자 외형 테마는 item_category 기반(정당히 공개되는 정보)이라 그대로 쓴다.
    if npc["npc_kind"] == "buyer":
        visual_theme = _buyer_theme_for(row["id"])
    else:
        visual_theme = npc["visual_theme"] or "general_booth"

    # 말풍선 문구(tagline)는 정답을 노출하지 않는 공개 정보 → personas 에서 가져온다.
    from app.ai.personas import npc_by_id
    src = npc_by_id(row["npc_id"])
    tagline = (src.get("tagline") if src else None) or npc["item_name"]

    return {
        "spawn_instance_id": row["id"],
        "npc_kind": npc["npc_kind"],
        "name": npc["name"],
        "item_name": npc["item_name"],
        "item_category": npc["item_category"],
        "category": npc["category"] or "general",
        "visual_theme": visual_theme,
        "tagline": tagline,
        "listing_price": npc["listing_price"],
        "sprite_color": npc["sprite_color"],
        "x": row["x"],
        "y": row["y"],
        "remaining_seconds": remaining,
    }


def _expire_old(conn: sqlite3.Connection, user_id: int, now: datetime) -> None:
    """수명이 끝난 스폰(활성/거래중)을 제거해 테이블을 깔끔히 유지한다."""
    rows = conn.execute(
        "SELECT id, expires_at FROM active_spawns "
        "WHERE user_id = ? AND status IN ('active', 'engaged')",
        (user_id,),
    ).fetchall()
    dead = [r["id"] for r in rows if _parse(r["expires_at"]) <= now]
    for sid in dead:
        conn.execute("DELETE FROM active_spawns WHERE id = ?", (sid,))


def _active_rows(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM active_spawns WHERE user_id = ? AND status = 'active' ORDER BY spawned_at",
        (user_id,),
    ).fetchall()


def _fill(conn: sqlite3.Connection, user: sqlite3.Row, profile: dict, now: datetime) -> None:
    """부족한 만큼 새 스폰을 채운다."""
    game_role = user["game_role"] or "buyer"
    kind = _eligible_kind(game_role)

    level = user["level"] if "level" in user.keys() else 1
    allowed = _allowed_difficulties(level)
    pool = conn.execute(
        "SELECT id, difficulty FROM npcs WHERE npc_kind = ?", (kind,)
    ).fetchall()
    pool_ids = [r["id"] for r in pool if (r["difficulty"] or "medium") in allowed]
    if not pool_ids:  # 필터로 전부 걸러지면(데이터 이상) 전체로 폴백
        pool_ids = [r["id"] for r in pool]
    if not pool_ids:
        return

    spots = list(profile["map"].get("vendor_spots", []))
    if not spots:
        return

    active = _active_rows(conn, user["id"])
    # 점유 판정은 '거래중(engaged)' 스폰까지 포함해야 한다.
    # 안 그러면 지금 거래 중인 NPC 가 같은 좌표/같은 NPC 로 또 등장(중복)할 수 있다.
    occupied = conn.execute(
        "SELECT npc_id, x, y FROM active_spawns "
        "WHERE user_id = ? AND status IN ('active', 'engaged')",
        (user["id"],),
    ).fetchall()
    used_xy = {(r["x"], r["y"]) for r in occupied}
    # 인물별 등장 횟수 (중복을 한쪽에 몰지 않고 고르게 퍼뜨리기 위함)
    use_count = {i: 0 for i in pool_ids}
    for r in occupied:
        if r["npc_id"] in use_count:
            use_count[r["npc_id"]] += 1

    # OS 엔트로피로 매번 새로 시드 → 모든 NPC/자리가 고르게 등장 (특정 유형 누락 방지).
    rnd = random.Random()

    # 풀(고유 NPC 수)보다 많이 띄우고 싶으면, 같은 인물이 '다른 자리'에 한두 번 더
    # 나오도록 허용한다(자리는 항상 서로 다름). 넓어진 동네를 북적이게 채우기 위함.
    target = min(_TARGET_ACTIVE, len(spots))
    guard = 0
    while len(active) < target and guard < 50:
        guard += 1
        free_spots = [s for s in spots if (s["x"], s["y"]) not in used_xy]
        if not free_spots:
            break
        # 가장 적게 등장한 인물부터 고른다 → 중복이 고르게 분산된다.
        least = min(use_count.values())
        npc_id = rnd.choice([i for i in pool_ids if use_count[i] == least])
        spot = rnd.choice(free_spots)
        lifetime = rnd.randint(_LIFETIME_MIN, _LIFETIME_MAX)
        sid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO active_spawns (id, user_id, npc_id, game_role, x, y, "
            "spawned_at, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')",
            (sid, user["id"], npc_id, game_role, spot["x"], spot["y"],
             now.isoformat(), (now + timedelta(seconds=lifetime)).isoformat()),
        )
        use_count[npc_id] += 1
        used_xy.add((spot["x"], spot["y"]))
        active = _active_rows(conn, user["id"])


def refresh_and_list(conn: sqlite3.Connection, user: sqlite3.Row, profile: dict) -> list[dict]:
    """만료 정리 + 부족분 채우기 → 현재 활성 스폰 공개 목록."""
    now = _now()
    _expire_old(conn, user["id"], now)
    _fill(conn, user, profile, now)
    out = []
    for row in _active_rows(conn, user["id"]):
        pub = _public_spawn(conn, row, now)
        if pub:
            out.append(pub)
    return out


def force_refresh(conn: sqlite3.Connection, user: sqlite3.Row, profile: dict) -> list[dict]:
    """전부 비우고 새로 채운다 (디버그/개발용)."""
    conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
    return refresh_and_list(conn, user, profile)


def engage(conn: sqlite3.Connection, user_id: int, spawn_instance_id: str | None) -> None:
    """대화 시작 시 해당 스폰을 활성 풀에서 빼서 '거래중'으로 표시 (best-effort)."""
    if not spawn_instance_id:
        return
    conn.execute(
        "UPDATE active_spawns SET status = 'engaged' WHERE id = ? AND user_id = ?",
        (spawn_instance_id, user_id),
    )
