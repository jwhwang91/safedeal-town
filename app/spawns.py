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


def _approach_params(spawn_id: str) -> tuple[float, int | None]:
    """판매자 모드 구매자 NPC 의 결정적 (관심도, 접근 지연초).

    역할(정상/빌런 등)과 '무관'하다 — 스폰 id 해시로만 정해서 정체가 새지 않게 한다.
    일부 구매자는 접근하지 않고(=None) 잠깐 둘러보다 사라진다 → 한꺼번에 몰리지 않음.
    """
    h = sum((i + 1) * ord(c) for i, c in enumerate(spawn_id)) if spawn_id else 0
    interest = round(0.35 + (h % 61) / 100.0, 2)  # 0.35 ~ 0.95
    bucket = (h // 7) % 100
    if bucket < 35:
        delay: int | None = 4 + (h % 7)       # 곧 다가옴 (4~10초)
    elif bucket < 70:
        delay = 22 + (h % 26)                 # 잠시 후 (22~47초)
    else:
        delay = None                          # 이번엔 둘러보기만 (접근 안 함)
    return interest, delay


def _augment_buyer_approach(pub: dict, ctx: dict) -> dict:
    """판매자 모드 구매자 NPC 스폰에 '접근/문의' 메타를 붙인다 (역할 비노출).

    approach_state 는 서버가 권위적으로 정한다:
      - 백엔드가 이 스폰에 '대기 문의(inquiry)'를 만들었으면 → "waiting" (+ inquiry_id/expires_at)
      - 아니면 → "roaming" (떠돌기만; 프론트는 다가오는 연출을 하지 않는다)
    이렇게 해야 max_pending/페이싱이 그대로 지켜지고, 한꺼번에 몰리지 않는다.
    inquiry_preview 는 플레이어 매물명을 가리키되 구매자 유형은 절대 드러내지 않는 중립 문구.
    """
    from app.ai import persona_factory

    sid = pub["spawn_instance_id"]
    interest, delay = _approach_params(sid)
    pub["target"] = "player"
    pub["interest_level"] = interest
    pub["approach_delay_seconds"] = delay

    inq = (ctx.get("inquiries_by_spawn") or {}).get(sid)
    if inq:
        # 서버가 만든 실제 문의 — 다가와서 문의 카드를 남긴 상태.
        pub["approach_state"] = "waiting"
        pub["inquiry_id"] = inq["id"]
        pub["inquiry_preview"] = inq["inquiry_preview"]
        pub["inquiry_created_at"] = inq["created_at"]
        pub["expires_at"] = inq["expires_at"]
        pub["inquiry_remaining_seconds"] = inq["remaining_seconds"]
    else:
        pub["approach_state"] = "roaming"
        pub["inquiry_id"] = None
        pub["inquiry_preview"] = persona_factory.neutral_inquiry_preview(
            ctx.get("seller_item"), sid
        )
    return pub


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


def _dynamic_of(row: sqlite3.Row) -> dict | None:
    """active_spawns 행에 저장된 동적 NPC(JSON)를 파싱. 없거나 깨졌으면 None."""
    raw = row["dynamic_json"] if "dynamic_json" in row.keys() else None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _public_spawn(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime,
                  ctx: dict | None = None) -> dict | None:
    """active_spawns 의 공개 가능한 필드만 추린다 (동적 NPC 우선, 없으면 npcs 테이블)."""
    ctx = ctx or {}
    remaining = max(0, int((_parse(row["expires_at"]) - now).total_seconds()))

    # 동적 NPC 가 있으면 그걸로 공개 카드를 만든다 (정답지는 절대 미포함).
    dyn = _dynamic_of(row)
    if dyn:
        npc_kind = dyn.get("npc_kind", "seller")
        # 구매자 NPC 외형 테마는 역할과 무관하게 스폰별로 (정체 추리 보호).
        if npc_kind == "buyer":
            visual_theme = _buyer_theme_for(row["id"])
        else:
            visual_theme = dyn.get("visual_theme") or "general_booth"
        pub = {
            "spawn_instance_id": row["id"],
            "npc_kind": npc_kind,
            "name": dyn.get("name"),
            "item_name": dyn.get("item_name"),
            "item_category": dyn.get("item_category"),
            "category": dyn.get("category") or "general",
            "visual_theme": visual_theme,
            "tagline": dyn.get("tagline") or dyn.get("item_name") or "",
            "listing_price": dyn.get("listing_price", 0),
            "sprite_color": dyn.get("sprite_color") or "#b0a080",
            # 얼굴 이미지: 스폰 id 만 담은 불투명 URL (family/role/gender 비노출).
            "portrait_url": f"/api/chat/portrait/{row['id']}",
            "x": row["x"],
            "y": row["y"],
            "remaining_seconds": remaining,
        }
        if npc_kind == "buyer":
            pub = _augment_buyer_approach(pub, ctx)
        return pub

    # 폴백: 정적 npcs 테이블 (동적 생성이 꺼졌거나 실패한 경우)
    npc = conn.execute(
        "SELECT id, name, item_name, item_category, listing_price, sprite_color, "
        "npc_kind, visual_theme, category FROM npcs WHERE id = ?",
        (row["npc_id"],),
    ).fetchone()
    if not npc:
        return None

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

    pub = {
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
        # 얼굴 이미지: 스폰 id 만 담은 불투명 URL (family/role/gender 비노출).
        "portrait_url": f"/api/chat/portrait/{row['id']}",
        "x": row["x"],
        "y": row["y"],
        "remaining_seconds": remaining,
    }

    # 구매자 모드 카테고리 강제: 동적 생성이 실패해 정적 판매자로 폴백했을 때
    # 사용자가 고른 카테고리와 다른 물건이 보이지 않도록, 공개 표시를 그 카테고리의
    # 합성 매물로 바꿔준다. ('random'/미지정이면 그대로 둔다 — 전 카테고리 허용.)
    want = (ctx.get("buyer_category") or "random")
    if npc["npc_kind"] == "seller" and want not in (None, "", "random"):
        from app.market import catalog
        want_canon = catalog.canonical_of(want)
        if (npc["category"] or "general") != want_canon and want in catalog.PRODUCTS:
            try:
                listing = catalog.generate_listing(want)
                pub["item_name"] = listing["item_name"]
                pub["item_category"] = listing["category_label"]
                pub["category"] = listing["canonical_category"]
                pub["visual_theme"] = listing["visual_theme"]
                pub["listing_price"] = listing["listing_price"]
                pub["tagline"] = listing["listing_title"]
            except Exception:
                pass  # 합성 실패해도 게임은 계속 (정적 표시 유지)

    if npc["npc_kind"] == "buyer":
        pub = _augment_buyer_approach(pub, ctx)
    return pub


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

    # 채울 자리가 있을 때만 동적 생성 재료(선호/판매글/매물 씨앗)를 준비한다.
    needed = max(0, target - len(active))
    dyn_ctx = _dynamic_context(conn, user, game_role, needed) if needed else None

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
        # 동적 NPC(매물/페르소나/대사)를 만들어 저장한다. 실패하면 정적 NPC 로 폴백(NULL).
        # sid 를 씨앗으로 넘겨 '얼굴을 먼저 고르고' 겉모습/성별/이름을 맞춘다(초상-우선).
        dynamic_json = _make_dynamic_json(npc_id, game_role, dyn_ctx, rnd, sid)
        conn.execute(
            "INSERT INTO active_spawns (id, user_id, npc_id, game_role, x, y, "
            "spawned_at, expires_at, status, dynamic_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (sid, user["id"], npc_id, game_role, spot["x"], spot["y"],
             now.isoformat(), (now + timedelta(seconds=lifetime)).isoformat(),
             dynamic_json),
        )
        use_count[npc_id] += 1
        used_xy.add((spot["x"], spot["y"]))
        active = _active_rows(conn, user["id"])


def _dynamic_context(conn, user, game_role, needed: int) -> dict:
    """동적 생성에 필요한 재료를 한 번만 모은다 (선호/판매글 + 매물 씨앗 배치)."""
    from app import preferences as prefs_mgr

    prefs = prefs_mgr.get_preferences(conn, user["id"])
    seeds: list = []
    if game_role != "seller":
        try:
            from app.market import fetch_seeds
            seeds = fetch_seeds(prefs.get("buyer_category", "random"), limit=max(needed, 4))
        except Exception:
            seeds = []
    return {"prefs": prefs, "seeds": seeds}


def _make_dynamic_json(npc_id, game_role, ctx, rnd, spawn_seed=None) -> str | None:
    """앵커(npc_id)에 매물/페르소나를 입혀 동적 NPC JSON 을 만든다. 실패 시 None.

    spawn_seed(스폰 id)는 '얼굴을 먼저 고르는' 초상-우선 생성에 쓰인다(서빙 때와 같은 시드).
    """
    if ctx is None:
        return None
    try:
        from app.ai import persona_factory
        from app.ai.personas import npc_by_id

        anchor = npc_by_id(npc_id)
        if not anchor:
            return None
        if game_role == "seller":
            dyn = persona_factory.generate_buyer_npc_for_seller_mode(
                anchor, ctx["prefs"].get("seller_listing"), rng=rnd, spawn_seed=spawn_seed
            )
        else:
            seeds = ctx.get("seeds") or []
            seed = seeds.pop() if seeds else None
            dyn = persona_factory.generate_seller_npc_for_buyer_mode(
                anchor, ctx["prefs"], listing_seed=seed, rng=rnd, spawn_seed=spawn_seed
            )
        return json.dumps(dyn, ensure_ascii=False)
    except Exception:
        # 동적 생성이 어떤 이유로든 실패해도 게임은 정적 NPC 로 계속된다.
        return None


def _public_context(conn: sqlite3.Connection, user: sqlite3.Row) -> dict:
    """공개 스폰 페이로드 가공에 필요한 사용자 맥락(선호/판매글)을 한 번만 모은다.

    - buyer_category: 구매자 모드 카테고리 강제용
    - seller_item:    판매자 모드 구매자 NPC 의 중립 문의 미리보기에 쓸 '내 매물명'
    """
    game_role = user["game_role"] or "buyer"
    try:
        from app import preferences as prefs_mgr
        prefs = prefs_mgr.get_preferences(conn, user["id"])
    except Exception:
        prefs = {}
    seller_listing = prefs.get("seller_listing") or {}
    # 판매자 모드: 현재 대기 중인 인바운드 문의를 spawn_id 로 매핑해 둔다(서버 권위 approach_state).
    inquiries_by_spawn: dict = {}
    if game_role == "seller":
        try:
            from app import inquiries as inquiry_mgr
            inquiries_by_spawn = inquiry_mgr.waiting_by_spawn(conn, user["id"])
        except Exception:
            inquiries_by_spawn = {}
    return {
        "game_role": game_role,
        "buyer_category": prefs.get("buyer_category", "random"),
        "seller_item": seller_listing.get("product_name") or seller_listing.get("item_name"),
        "inquiries_by_spawn": inquiries_by_spawn,
    }


def refresh_and_list(conn: sqlite3.Connection, user: sqlite3.Row, profile: dict) -> list[dict]:
    """만료 정리 + 부족분 채우기 → 현재 활성 스폰 공개 목록."""
    now = _now()
    _expire_old(conn, user["id"], now)
    _fill(conn, user, profile, now)
    # 판매자 모드: 인바운드 문의 수명/페이싱 갱신 (실패해도 게임은 계속).
    if (user["game_role"] or "buyer") == "seller":
        try:
            from app import inquiries as inquiry_mgr
            inquiry_mgr.refresh_for_user(conn, user, now)
        except Exception:
            pass
    ctx = _public_context(conn, user)
    out = []
    for row in _active_rows(conn, user["id"]):
        pub = _public_spawn(conn, row, now, ctx)
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
