"""
판매자 모드 인바운드 문의 시스템 (백엔드 관리).

판매글을 올리면 구매자 NPC 들이 마을을 돌아다니다가 '하나둘' 문의를 보낸다.
이 모듈이 그 '문의(inquiry)'의 수명/페이싱을 서버에서 관리한다:

  - 마을에는 여러 구매자 NPC 가 떠돌지만(roaming), 그중 일부만 실제로 다가와
    '문의 카드'를 남긴다(waiting).
  - 새 문의는 한꺼번에 몰리지 않게 무작위 간격을 두고 생긴다 (페이싱).
  - 대기 중인 문의는 최대 SELLER_MAX_PENDING_INQUIRIES 개로 제한된다.
  - 문의는 수명(expires_at)이 지나면 사라진다(구매자가 흥미를 잃음).
  - 구매자 NPC 스폰이 사라지면 FK CASCADE 로 해당 문의도 자동 삭제된다.
  - 플레이어가 문의를 '수락(accept)'하면 그 구매자와 거래(채팅)가 시작된다.

정답지 보호: 문의는 '중립 미리보기(상품명만 가리킴)'만 노출한다. 구매자의 숨은 유형
(정상/환불빌런/막깎이…)은 절대 드러내지 않는다. npc_id(앵커)는 서버 전용이다.

이 모듈은 spawns.refresh_and_list(판매자 모드)에서 호출되어, 스폰 폴링(약 6초)마다
문의 수명/생성을 갱신한다. 실패해도 게임은 그대로 동작하도록 호출부가 best-effort 로 감싼다.
"""
from __future__ import annotations

import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from app.config import get_settings

# 첫 문의는 판매자 모드 진입 후 비교적 일찍(스폰 등장 기준). 이후 문의는 config 간격을 따른다.
_FIRST_INQUIRY_MIN_SECONDS = 8
_FIRST_INQUIRY_MAX_SECONDS = 20

# 문의 카드 수명(구매자가 흥미를 잃기 전까지 카드가 떠 있는 시간). 스폰 잔여수명으로 추가 제한된다.
_INQUIRY_TTL_MIN_SECONDS = 35
_INQUIRY_TTL_MAX_SECONDS = 80

# '다가오는 중'으로 간주하는 최근 생성 윈도(초). 이 안에 생긴 문의 수를 max_approaching 으로 제한.
_APPROACHING_WINDOW_SECONDS = 12


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _deterministic_gap(seed: str, lo: int, hi: int) -> int:
    """seed(사용자+기준시각)로 결정적인 간격(초)을 뽑는다 → 폴링마다 게이트가 흔들리지 않는다."""
    if hi <= lo:
        return max(1, lo)
    h = sum((i + 1) * ord(c) for i, c in enumerate(seed)) if seed else 0
    return lo + (h % (hi - lo + 1))


# ============================================================
#  내부 조회
# ============================================================
def _seller_item(conn: sqlite3.Connection, user_id: int) -> str | None:
    """현재 판매글의 상품명 (중립 문의 미리보기에 쓰임)."""
    try:
        from app import preferences as prefs_mgr
        listing = prefs_mgr.get_seller_listing(conn, user_id) or {}
    except Exception:
        listing = {}
    return listing.get("product_name") or listing.get("item_name")


def _active_buyer_spawns(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    """판매자 모드에서 현재 살아있는 구매자 NPC 스폰들 (active)."""
    return conn.execute(
        "SELECT id, npc_id, spawned_at, expires_at FROM active_spawns "
        "WHERE user_id = ? AND game_role = 'seller' AND status = 'active' "
        "ORDER BY spawned_at",
        (user_id,),
    ).fetchall()


# ============================================================
#  수명/페이싱 갱신 (스폰 폴링마다 호출)
# ============================================================
def refresh_for_user(conn: sqlite3.Connection, user: sqlite3.Row, now: datetime | None = None) -> None:
    """만료된 문의 정리 + 페이싱에 맞춰 새 문의 생성 (판매자 모드 전용).

    호출 전 spawns._expire_old 가 죽은 스폰을 지웠다면, FK CASCADE 로 그 스폰의 문의도
    이미 사라진 상태다. 여기서는 '수명이 다한 대기 문의'를 추가로 정리하고, 페이싱이 허락하면
    떠도는 구매자 하나를 골라 새 문의를 만든다.
    """
    if (user["game_role"] or "buyer") != "seller":
        return
    settings = get_settings()
    now = now or _now()
    now_iso = now.isoformat()
    uid = user["id"]

    # 1) 수명이 다한 '대기' 문의 제거 → 카드가 사라진다. (수락된 문의는 세션과 연결돼 보존)
    conn.execute(
        "DELETE FROM seller_inquiries "
        "WHERE user_id = ? AND status = 'waiting' AND expires_at <= ?",
        (uid, now_iso),
    )

    # 2) 현재 대기 중인 문의 수 / 막 생긴(다가오는 중) 문의 수
    waiting = conn.execute(
        "SELECT spawn_id, created_at FROM seller_inquiries "
        "WHERE user_id = ? AND status = 'waiting'",
        (uid,),
    ).fetchall()
    max_pending = max(1, settings.seller_max_pending_inquiries)
    if len(waiting) >= max_pending:
        return  # 이미 꽉 참 — 더 안 만든다.

    max_approaching = max(1, settings.seller_max_approaching_buyers)
    approaching = sum(
        1 for w in waiting
        if (now - _parse(w["created_at"])).total_seconds() <= _APPROACHING_WINDOW_SECONDS
    )
    if approaching >= max_approaching:
        return  # 한꺼번에 너무 많이 다가오지 않게.

    # 3) 페이싱 게이트: 마지막 문의 생성 시각 + 무작위 간격이 지나야 새 문의 허용.
    last = conn.execute(
        "SELECT MAX(created_at) AS last FROM seller_inquiries WHERE user_id = ?",
        (uid,),
    ).fetchone()
    spawns = _active_buyer_spawns(conn, uid)
    if not spawns:
        return  # 떠도는 구매자가 없으면 문의도 없다.

    if last and last["last"]:
        base = _parse(last["last"])
        gap = _deterministic_gap(
            f"{uid}:{last['last']}",
            settings.seller_inquiry_min_delay_seconds,
            settings.seller_inquiry_max_delay_seconds,
        )
    else:
        # 첫 문의: 판매자 모드 진입(가장 이른 구매자 스폰 등장) 기준으로 일찍.
        base = _parse(spawns[0]["spawned_at"])
        gap = _deterministic_gap(
            f"{uid}:first", _FIRST_INQUIRY_MIN_SECONDS, _FIRST_INQUIRY_MAX_SECONDS
        )
    if now < base + timedelta(seconds=gap):
        return  # 아직 간격이 안 됨.

    # 4) 아직 문의를 남기지 않은(대기/수락 모두 아님) 떠도는 구매자 후보를 고른다.
    taken = {
        r["spawn_id"] for r in conn.execute(
            "SELECT spawn_id FROM seller_inquiries "
            "WHERE user_id = ? AND status IN ('waiting', 'accepted')",
            (uid,),
        ).fetchall()
    }
    candidates = [s for s in spawns if s["id"] not in taken]
    if not candidates:
        return

    rnd = random.Random()
    # 5) 무작위 관심: 매 폴링마다 항상 다가오진 않는다 (자연스러운 띄엄띄엄함).
    if rnd.random() < 0.45:
        return  # 이번엔 그냥 둘러보기만.

    spawn = rnd.choice(candidates)
    item = _seller_item(conn, uid)
    listing_title = item or "내 매물"
    try:
        from app.ai import persona_factory
        preview = persona_factory.neutral_inquiry_preview(item, spawn["id"])
    except Exception:
        preview = "이거 아직 판매 중인가요?"

    # 6) 문의 수명: 무작위 TTL, 단 스폰 잔여수명을 넘지 않게 캡.
    ttl = rnd.randint(_INQUIRY_TTL_MIN_SECONDS, _INQUIRY_TTL_MAX_SECONDS)
    expires = now + timedelta(seconds=ttl)
    spawn_expires = _parse(spawn["expires_at"])
    if spawn_expires < expires:
        expires = spawn_expires

    conn.execute(
        "INSERT INTO seller_inquiries "
        "(id, user_id, spawn_id, npc_id, listing_title, inquiry_preview, status, "
        " created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?, ?)",
        (str(uuid.uuid4()), uid, spawn["id"], spawn["npc_id"], listing_title[:60],
         preview[:120], now_iso, expires.isoformat()),
    )


# ============================================================
#  조회 (직렬화/카드용)
# ============================================================
def waiting_by_spawn(conn: sqlite3.Connection, user_id: int, now: datetime | None = None) -> dict:
    """{spawn_id: inquiry_dict} — 스폰 공개 페이로드에 문의 상태를 입힐 때 쓴다."""
    now = now or _now()
    rows = conn.execute(
        "SELECT id, spawn_id, inquiry_preview, created_at, expires_at "
        "FROM seller_inquiries WHERE user_id = ? AND status = 'waiting'",
        (user_id,),
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        remaining = max(0, int((_parse(r["expires_at"]) - now).total_seconds()))
        out[r["spawn_id"]] = {
            "id": r["id"],
            "inquiry_preview": r["inquiry_preview"],
            "created_at": r["created_at"],
            "expires_at": r["expires_at"],
            "remaining_seconds": remaining,
        }
    return out


def list_waiting(conn: sqlite3.Connection, user_id: int, now: datetime | None = None) -> list[dict]:
    """GET /api/game/inquiries 용 — 대기 중인 문의 목록 (스폰 공개 정보와 조인).

    정답지(npc_id/role)는 절대 포함하지 않는다. 스폰이 살아있는 문의만 돌려준다.
    """
    now = now or _now()
    rows = conn.execute(
        """
        SELECT si.id, si.spawn_id, si.inquiry_preview, si.listing_title,
               si.created_at, si.expires_at,
               sp.x AS x, sp.y AS y, sp.dynamic_json AS dynamic_json,
               sp.npc_id AS spawn_npc_id
        FROM seller_inquiries si
        JOIN active_spawns sp ON sp.id = si.spawn_id
        WHERE si.user_id = ? AND si.status = 'waiting'
        ORDER BY si.created_at
        """,
        (user_id,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        if _parse(r["expires_at"]) <= now:
            continue  # 만료된 건 다음 refresh 가 정리한다.
        nickname = _spawn_nickname(conn, r)
        remaining = max(0, int((_parse(r["expires_at"]) - now).total_seconds()))
        out.append({
            "inquiry_id": r["id"],
            "spawn_instance_id": r["spawn_id"],
            "npc_kind": "buyer",
            "nickname": nickname,
            "inquiry_preview": r["inquiry_preview"],
            "listing_title": r["listing_title"],
            "x": r["x"],
            "y": r["y"],
            "remaining_seconds": remaining,
        })
    return out


def _spawn_nickname(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    """문의를 남긴 구매자의 표시 닉네임 (동적 NPC 우선, 정답지 비노출)."""
    import json

    raw = row["dynamic_json"] if "dynamic_json" in row.keys() else None
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("name"):
                return str(data["name"])
        except (json.JSONDecodeError, TypeError):
            pass
    npc = conn.execute(
        "SELECT name FROM npcs WHERE id = ?", (row["spawn_npc_id"],)
    ).fetchone()
    return (npc["name"] if npc else None) or "구매자"


# ============================================================
#  수락 (채팅 시작 연결)
# ============================================================
def spawn_id_for(conn: sqlite3.Connection, user_id: int, inquiry_id: str,
                 now: datetime | None = None) -> str | None:
    """대기 중인 문의의 spawn_id 를 돌려준다. 본인 소유 + 대기 상태 + 미만료 + 스폰 생존일 때만.

    list_waiting 과 동일한 만료 기준(expires_at > now)을 적용한다 → 화면에서 이미 사라진
    카드를 뒤늦게 수락하는 일을 막아 읽기/수락 동작을 일관되게 한다.
    """
    now = now or _now()
    row = conn.execute(
        """
        SELECT si.spawn_id FROM seller_inquiries si
        JOIN active_spawns sp ON sp.id = si.spawn_id
        WHERE si.id = ? AND si.user_id = ? AND si.status = 'waiting'
              AND si.expires_at > ?
        """,
        (inquiry_id, user_id, now.isoformat()),
    ).fetchone()
    return row["spawn_id"] if row else None


def claim_inquiry(conn: sqlite3.Connection, user_id: int, inquiry_id: str,
                  session_id: str, now: datetime | None = None) -> bool:
    """대기 중인 문의를 '수락됨'으로 원자적으로 선점한다 (중복 수락/중복 세션 방지).

    조건부 UPDATE(WHERE status='waiting' AND 미만료)가 정확히 1행을 바꿨을 때만 True 다.
    이미 수락됐거나 만료됐거나 남의 문의면 0행 → False. SQLite 의 쓰기 락이 동시 수락을
    직렬화하므로, 두 요청이 같은 문의를 동시에 수락해도 한쪽만 1행을 얻는다.
    호출부는 False 면 거래 세션을 만들지 말고 거절(409)해야 한다.
    """
    now = now or _now()
    cur = conn.execute(
        "UPDATE seller_inquiries SET status = 'accepted', session_id = ? "
        "WHERE id = ? AND user_id = ? AND status = 'waiting' AND expires_at > ?",
        (session_id, inquiry_id, user_id, now.isoformat()),
    )
    return cur.rowcount == 1
