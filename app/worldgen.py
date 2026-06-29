"""
절차적 동네 생성기 (서버측, 시드 기반).

맵을 '한 곳'에서만 만든다 — 백엔드. 프론트(world_map.js)는 그저 받은 대로 그린다.
이렇게 하면 시드/지형 로직이 두 언어에 흩어지지 않는다.

핵심:
  - 같은 시드 → 항상 같은 동네 (결정적). random.Random(seed) 만 사용.
  - 위치(대략 위경도)를 주면 그걸 시드로 → 사람마다 동네가 달라진다.
  - 위치를 안 줘도(거부해도) 사용자 고유 시드로 항상 생성된다.
  - 제공자(provider)는 라벨일 뿐. google/naver 키가 없거나 거부돼도
    동일한 '도트/픽셀 스타일 절차적 동네'를 그린다 (항상 동작 보장).

반환하는 map dict 구조 (프론트와의 계약):
  cols, rows, tile, provider, seed,
  tiles[][]   : 바닥 타일 코드
  solid[][]   : 충돌 격자 (true=못 지나감)
  buildings[] : {x,y,w,h,category,name,color}
  landmarks[] : {x,y,type,name}
  vendor_spots[] : [{x,y}, ...]  NPC 가 설 수 있는 보행 가능 칸
  player_spawn: {x,y}
"""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timezone

from app.config import get_settings

# 동네는 화면(24x16 타일)보다 크게 만든다 → 카메라가 플레이어를 따라가며 스크롤되고,
# 돌아다닐수록 새 구역이 드러난다("맵이 넓어지는" 느낌). 프론트는 보이는 부분만 그린다.
COLS = 40
ROWS = 28
TILE = 40

# 바닥 타일 코드 (프론트 world_map.js 와 공유)
T_GRASS = 0
T_ROAD = 1
T_SIDEWALK = 2
T_PLAZA = 3
T_PARK = 4
T_WATER = 5

# 가게 카테고리 프리셋: (간판이름, 벽색)
_SHOP_PRESETS = {
    "electronics": ("전자마트", "#6b8cce"),
    "fashion":     ("옷가게",   "#d98aa8"),
    "beauty":      ("뷰티샵",   "#e0a0c0"),
    "home":        ("생활공방", "#caa06a"),
    "books":       ("책방",     "#8aa86a"),
    "camping":     ("캠핑상점", "#6aae8a"),
    "cafe":        ("카페",     "#c98a5a"),
    "general":     ("잡화점",   "#b0a080"),
}
_SHOP_ORDER = ["electronics", "fashion", "beauty", "cafe", "home", "books", "camping", "general"]

# 위치 라벨이 없을 때 쓰는 귀여운 동네 이름 후보 (시드로 결정적 선택).
_TOWN_ADJECTIVES = [
    "햇살", "보름달", "단풍", "물안개", "들꽃", "노을", "솔바람", "도토리", "민들레", "별빛",
]


def _town_name(rnd: random.Random, place_label: str | None) -> str:
    """화면에 보일 동네 이름. 위치를 알면 '○○ 중고타운', 모르면 시드 기반 귀여운 이름."""
    label = (place_label or "").strip()
    if label:
        return f"{label} 중고타운"
    return f"{rnd.choice(_TOWN_ADJECTIVES)}마을 중고타운"


def _seed_int(seed_str: str) -> int:
    return int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:12], 16)


def _seed_string(user: sqlite3.Row, lat: float | None, lng: float | None) -> str:
    if lat is not None and lng is not None:
        return f"geo:{lat:.2f},{lng:.2f}"
    return f"user:{user['id']}:{user['username']}"


def generate_map(seed_str: str, provider: str, place_label: str | None = None) -> dict:
    """시드 문자열로 결정적 동네 하나를 만든다."""
    rnd = random.Random(_seed_int(seed_str))

    tiles = [[T_GRASS for _ in range(COLS)] for _ in range(ROWS)]
    solid = [[False for _ in range(COLS)] for _ in range(ROWS)]

    # 1) 바깥 울타리 (못 지나감)
    for x in range(COLS):
        solid[0][x] = solid[ROWS - 1][x] = True
    for y in range(ROWS):
        solid[y][0] = solid[y][COLS - 1] = True

    # 2) 도로망 — 일정 간격의 격자 도로 (시드로 간격/시작 위치 변주).
    #    맵 크기(COLS/ROWS)에 맞춰 자동으로 줄 수가 늘어난다.
    v_gap = rnd.choice([7, 8, 9])
    h_gap = rnd.choice([6, 7, 8])
    v_roads = list(range(rnd.randint(3, v_gap), COLS - 2, v_gap))
    h_roads = list(range(rnd.randint(3, h_gap), ROWS - 2, h_gap))
    if not v_roads:
        v_roads = [COLS // 2]
    if not h_roads:
        h_roads = [ROWS // 2]

    for x in v_roads:
        for y in range(1, ROWS - 1):
            tiles[y][x] = T_ROAD
    for y in h_roads:
        for x in range(1, COLS - 1):
            tiles[y][x] = T_ROAD

    # 3) 인도 — 도로에 붙은 잔디칸
    for y in range(1, ROWS - 1):
        for x in range(1, COLS - 1):
            if tiles[y][x] != T_GRASS:
                continue
            if any(
                0 <= y + dy < ROWS and 0 <= x + dx < COLS and tiles[y + dy][x + dx] == T_ROAD
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ):
                tiles[y][x] = T_SIDEWALK

    landmarks: list[dict] = []

    # 4) 광장 — 한 교차로 주변을 광장으로 + 분수
    px, py = rnd.choice(v_roads), rnd.choice(h_roads)
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            ny, nx = py + dy, px + dx
            if 0 < ny < ROWS - 1 and 0 < nx < COLS - 1:
                tiles[ny][nx] = T_PLAZA
                solid[ny][nx] = False
    landmarks.append({"x": px, "y": py, "type": "fountain", "name": "분수"})
    solid[py][px] = True  # 분수는 못 지나감

    # 5) 공원 — 도로가 없는 한 블록을 골라 잔디공원 + 나무/벤치
    park = _find_block_rect(tiles, rnd, w=4, h=3)
    if park:
        x0, y0, w, h = park
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                tiles[y][x] = T_PARK
        # 나무 몇 그루 (못 지나감)
        for _ in range(rnd.randint(2, 4)):
            tx = rnd.randint(x0, x0 + w - 1)
            ty = rnd.randint(y0, y0 + h - 1)
            if not solid[ty][tx]:
                solid[ty][tx] = True
                landmarks.append({"x": tx, "y": ty, "type": "tree", "name": "나무"})
        landmarks.append({"x": x0, "y": y0 + h - 1, "type": "bench", "name": "벤치"})

    # 5b) 연못 — 동네마다 다르게(시드 기반) 작은 물 블록을 둔다.
    #     위치(=좌표 시드)에 따라 어떤 동네는 물가, 어떤 동네는 없음 → 지역색.
    #     물은 못 지나간다(solid). 도로/광장을 막지 않도록 빈 잔디 블록에만 만든다.
    for _ in range(rnd.choice([0, 1, 1, 2])):
        pw, ph = rnd.choice([(3, 2), (2, 2), (3, 3), (4, 2)])
        pond = _find_block_rect(tiles, rnd, w=pw, h=ph)
        if pond:
            x0, y0, w, h = pond
            for y in range(y0, y0 + h):
                for x in range(x0, x0 + w):
                    tiles[y][x] = T_WATER
                    solid[y][x] = True
            landmarks.append({"x": x0, "y": y0, "type": "pond", "name": "연못"})

    # 6) 건물 — 잔디 블록 안쪽에 직사각형 가게들
    buildings: list[dict] = []
    shop_i = 0
    attempts = 0
    # 가게 수는 맵 면적에 비례 (넓은 동네일수록 가게도 많이).
    target = max(8, (COLS * ROWS) // 60 + rnd.randint(-1, 2))
    while len(buildings) < target and attempts < 800:
        attempts += 1
        bw = rnd.choice([2, 3])
        bh = rnd.choice([2, 2, 3])
        bx = rnd.randint(1, COLS - 1 - bw)
        by = rnd.randint(1, ROWS - 1 - bh)
        if _rect_is_free(tiles, solid, bx, by, bw, bh):
            cat = _SHOP_ORDER[shop_i % len(_SHOP_ORDER)]
            shop_i += 1
            name, color = _SHOP_PRESETS[cat]
            for y in range(by, by + bh):
                for x in range(bx, bx + bw):
                    solid[y][x] = True
                    tiles[y][x] = T_GRASS
            buildings.append({
                "x": bx, "y": by, "w": bw, "h": bh,
                "category": cat, "name": name, "color": color,
            })

    # 가로등 몇 개 (장식, 안 막음 — 점 표시만)
    for _ in range(rnd.randint(2, 4)):
        lx = rnd.randint(1, COLS - 2)
        ly = rnd.randint(1, ROWS - 2)
        if tiles[ly][lx] in (T_SIDEWALK, T_PLAZA) and not solid[ly][lx]:
            landmarks.append({"x": lx, "y": ly, "type": "lamp", "name": "가로등"})

    # 7) 벤더 스폿 — NPC 가 설 수 있는 보행 가능 칸 (도로/광장에 인접)
    vendor_spots = _collect_vendor_spots(tiles, solid, rnd)

    # 8) 플레이어 시작점 — 광장 근처 보행 가능 칸
    player_spawn = _pick_player_spawn(tiles, solid, px, py)

    return {
        "cols": COLS, "rows": ROWS, "tile": TILE,
        "provider": provider, "seed": seed_str,
        "place_label": place_label,            # 대략 도시/구 이름 (없으면 None)
        "town_name": _town_name(rnd, place_label),  # 화면에 보일 동네 이름
        "tiles": tiles, "solid": solid,
        "buildings": buildings, "landmarks": landmarks,
        "vendor_spots": vendor_spots,
        "player_spawn": player_spawn,
    }


def _rect_is_free(tiles, solid, bx, by, bw, bh) -> bool:
    """직사각형 영역이 전부 '빈 잔디'이고, 가장자리 한 겹도 비어 도로를 막지 않는지."""
    for y in range(by - 1, by + bh + 1):
        for x in range(bx - 1, bx + bw + 1):
            if not (0 <= y < ROWS and 0 <= x < COLS):
                return False
            inside = (by <= y < by + bh) and (bx <= x < bx + bw)
            if inside:
                if tiles[y][x] != T_GRASS or solid[y][x]:
                    return False
            else:
                # 둘레는 도로/광장이면 안 됨(가게가 길을 막지 않게), 다른 건물과도 안 붙게
                if solid[y][x]:
                    return False
    return True


def _find_block_rect(tiles, rnd, w, h):
    """도로/광장이 없는 잔디 직사각형 위치를 하나 찾는다 (공원용)."""
    candidates = []
    for y0 in range(1, ROWS - 1 - h):
        for x0 in range(1, COLS - 1 - w):
            ok = all(
                tiles[y][x] == T_GRASS
                for y in range(y0, y0 + h)
                for x in range(x0, x0 + w)
            )
            if ok:
                candidates.append((x0, y0, w, h))
    return rnd.choice(candidates) if candidates else None


def _collect_vendor_spots(tiles, solid, rnd) -> list[dict]:
    """도로/광장에 인접한 보행 가능 칸들. NPC 가 여기 선다."""
    spots = []
    for y in range(1, ROWS - 1):
        for x in range(1, COLS - 1):
            if solid[y][x]:
                continue
            if tiles[y][x] not in (T_SIDEWALK, T_PLAZA, T_PARK):
                continue
            near_path = any(
                0 <= y + dy < ROWS and 0 <= x + dx < COLS
                and tiles[y + dy][x + dx] in (T_ROAD, T_PLAZA)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            if near_path:
                spots.append({"x": x, "y": y})
    rnd.shuffle(spots)
    return spots


def _pick_player_spawn(tiles, solid, px, py) -> dict:
    """광장 중심 근처의 보행 가능 칸."""
    for dy, dx in ((0, 0), (1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, -1)):
        ny, nx = py + dy, px + dx
        if 0 < ny < ROWS - 1 and 0 < nx < COLS - 1 and not solid[ny][nx]:
            return {"x": nx, "y": ny}
    # 폴백: 아무 보행 가능 칸
    for y in range(1, ROWS - 1):
        for x in range(1, COLS - 1):
            if not solid[y][x]:
                return {"x": x, "y": y}
    return {"x": COLS // 2, "y": ROWS // 2}


# ============================================================
#  맵 프로필 저장/로드
# ============================================================
def _store(conn, user_id, provider, lat, lng, seed_str, map_obj) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO map_profiles (user_id, provider, lat, lng, seed, map_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            provider = excluded.provider,
            lat      = excluded.lat,
            lng      = excluded.lng,
            seed     = excluded.seed,
            map_json = excluded.map_json,
            updated_at = excluded.updated_at
        """,
        (user_id, provider, lat, lng, seed_str,
         json.dumps(map_obj, ensure_ascii=False), now),
    )
    return {"provider": provider, "seed": seed_str, "lat": lat, "lng": lng, "map": map_obj}


def build_and_store_profile(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    *,
    lat: float | None = None,
    lng: float | None = None,
    place_label: str | None = None,
    requested_provider: str | None = None,
) -> dict:
    """새 맵을 생성해 저장하고 프로필 dict 를 돌려준다.

    place_label 은 대략 도시/구 이름(IP 추정 또는 좌표 역지오코딩 결과)으로,
    화면에 동네 이름으로 표시된다. 맵 모양은 (lat,lng) 시드로 결정된다.
    """
    settings = get_settings()
    provider = settings.map_provider_effective
    # 프론트가 굳이 procedural 을 요청하면 존중 (다운그레이드만 허용)
    if requested_provider == "procedural":
        provider = "procedural"
    seed_str = _seed_string(user, lat, lng)
    map_obj = generate_map(seed_str, provider, place_label=place_label)
    return _store(conn, user["id"], provider, lat, lng, seed_str, map_obj)


def mark_geo_attempted(conn: sqlite3.Connection, user: sqlite3.Row, profile: dict) -> dict:
    """
    IP 위치추정을 시도했음을 맵에 표시(geo_attempted)하고 다시 저장한다.
    추정이 실패(네트워크 없음 등)했을 때, 게임 입장마다 외부 호출을 반복하지
    않도록 하는 표식. 좌표/시드/맵 모양은 그대로 둔다.
    """
    profile["map"]["geo_attempted"] = True
    return _store(
        conn, user["id"], profile["provider"],
        profile.get("lat"), profile.get("lng"), profile["seed"], profile["map"],
    )


def get_or_build_profile(conn: sqlite3.Connection, user: sqlite3.Row) -> dict:
    """저장된 맵 프로필을 불러오거나, 없으면 사용자 시드로 새로 만든다."""
    row = conn.execute(
        "SELECT provider, lat, lng, seed, map_json FROM map_profiles WHERE user_id = ?",
        (user["id"],),
    ).fetchone()
    if row:
        try:
            map_obj = json.loads(row["map_json"])
            ok = isinstance(map_obj, dict)
            # 구버전 맵 크기가 다르면(예: 24x16 → 40x28) 같은 위치/시드로 새 크기로 다시 만든다.
            if ok and (map_obj.get("cols") != COLS or map_obj.get("rows") != ROWS):
                label = map_obj.get("place_label")
                map_obj = generate_map(row["seed"] or "", row["provider"], place_label=label)
                _store(conn, user["id"], row["provider"], row["lat"], row["lng"],
                       row["seed"], map_obj)
                # 크기가 바뀌면 옛 스폰 좌표는 무효 → 비우고 새 맵 위에서 채운다.
                conn.execute("DELETE FROM active_spawns WHERE user_id = ?", (user["id"],))
            # 구버전 보정: town_name 이 없으면 시드로 동네 이름을 채운다.
            elif ok and "town_name" not in map_obj:
                rnd = random.Random(_seed_int(row["seed"] or ""))
                map_obj["place_label"] = map_obj.get("place_label")
                map_obj["town_name"] = _town_name(rnd, map_obj.get("place_label"))
            if ok:
                return {
                    "provider": row["provider"],
                    "seed": row["seed"],
                    "lat": row["lat"],
                    "lng": row["lng"],
                    "map": map_obj,
                }
        except (json.JSONDecodeError, TypeError):
            pass  # 깨졌으면 다시 생성
    return build_and_store_profile(conn, user)
