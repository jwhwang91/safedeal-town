"""
보상 + 인벤토리(거래 가방) 시스템.

거래를 마치면 XP/신뢰도/코인 외에 '거래 도구·신뢰 배지·코스튬'을 얻을 수 있다.
보상은 '현실적인 안전 거래 습관'을 장려하도록 설계한다 (판타지 능력 X):
  - 도구: 더 나은 체크리스트/힌트/빠른 답변칩을 제공 (정답을 대신 알려주지 않음).
  - 배지/코스튬: 아바타·프로필에 반영되고, NPC 대화에 '현실적인' 영향만 준다.
    (예: 신뢰 배지를 단 상대에겐 사기꾼이 더 조심스러워지는 식 — '약해지는' 게 아님)

이 모듈이 담당하는 것:
  - 기본 아이템 정의(ITEM_DEFS) + 시드(seed_default_items, 안전한 UPSERT)
  - 보상 굴리기(roll_item_rewards) + 지급(grant_item) + 결과 요약(calculate_trade_rewards)
  - 인벤토리 조회/장착/해제 + 장착 효과(도구 효과키 / 코스튬 아바타 오버라이드 / 배지)

희귀도: common(흔함) < uncommon < rare < epic < legendary(고난도 완벽 플레이의 드문 드랍)
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import datetime, timezone

# ============================================================
#  슬롯 정의
# ============================================================
COSMETIC_SLOTS = {"hat", "shirt", "pants", "accessory", "profile_frame"}
TOOL_SLOTS = {"tool_1", "tool_2"}
BADGE_SLOT = "badge"
ALL_SLOTS = COSMETIC_SLOTS | TOOL_SLOTS | {BADGE_SLOT}

RARITY_ORDER = ["common", "uncommon", "rare", "epic", "legendary"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
#  기본 아이템 정의
# ============================================================
# visual: 코스튬은 {"avatar": {slot: value}} 로 아바타 렌더에 반영된다.
#         도구/배지는 effect_key 로 게임플레이(힌트/체크리스트)에 반영된다.
def _item(id, name, item_type, rarity, slot, description, effect_key=None, visual=None):
    return {
        "id": id, "name": name, "item_type": item_type, "rarity": rarity,
        "slot": slot, "description": description, "effect_key": effect_key,
        "visual": visual or {},
    }


ITEM_DEFS = [
    # ---------- 코스튬 (아바타 반영) ----------
    _item("cos_retro_bag", "레트로 거래 가방", "cosmetic", "common", "accessory",
          "장터를 누빈 흔적이 묻은 가방.", visual={"avatar": {"accessory": "bag"}}),
    _item("cos_electronics_tee", "전자제품 덕후 티셔츠", "cosmetic", "common", "shirt",
          "전자기기를 사랑하는 마음이 담긴 티셔츠.", visual={"avatar": {"shirt": "plum"}}),
    _item("cos_safe_jacket", "안전거래 재킷", "cosmetic", "uncommon", "shirt",
          "안전거래를 상징하는 단정한 재킷.", visual={"avatar": {"shirt": "sky"}}),
    _item("cos_camping_look", "캠핑 마스터 룩", "cosmetic", "uncommon", "shirt",
          "캠핑 고수의 분위기가 나는 옷.", visual={"avatar": {"shirt": "sage"}}),
    _item("cos_detective_glasses", "탐정 안경", "cosmetic", "rare", "accessory",
          "수상한 신호를 놓치지 않는 탐정의 안경.", visual={"avatar": {"accessory": "sunglasses"}}),
    _item("cos_veteran_hood", "베테랑 거래자 후드", "cosmetic", "rare", "hat",
          "수많은 거래를 겪은 베테랑의 후드.", visual={"avatar": {"hat": "hood"}}),
    _item("cos_market_master_hat", "장터 고수 모자", "cosmetic", "epic", "hat",
          "장터의 고수만 쓴다는 모자.", visual={"avatar": {"hat": "detective"}}),

    # ---------- 프로필 프레임 ----------
    _item("frame_gold", "황금 거래 프레임", "profile_frame", "epic", "profile_frame",
          "프로필을 빛내는 황금 테두리.", effect_key="frame_gold",
          visual={"frame": "gold"}),

    # ---------- 신뢰 배지 (대화에 현실적 영향) ----------
    _item("badge_10_safe", "10회 무사고 거래 배지", "badge", "uncommon", BADGE_SLOT,
          "무사고 거래를 쌓아온 증표.", effect_key="trust_badge"),
    _item("badge_block_link", "외부 링크 차단 배지", "badge", "uncommon", BADGE_SLOT,
          "외부 링크를 단호히 거절한 증표.", effect_key="link_savvy"),
    _item("badge_refuse_prepay", "선입금 거절 배지", "badge", "rare", BADGE_SLOT,
          "선입금 요구를 막아낸 증표.", effect_key="prepay_savvy"),
    _item("badge_disclosure", "하자 고지 우수 판매자 배지", "badge", "rare", BADGE_SLOT,
          "하자를 정직하게 고지한 판매자의 증표.", effect_key="disclosure_pro"),
    _item("badge_calm", "분쟁 대응 침착왕 배지", "badge", "epic", BADGE_SLOT,
          "분쟁에서도 침착함을 잃지 않은 증표.", effect_key="calm_pro"),
    _item("badge_spotter", "정상 판매자 구분 배지", "badge", "rare", BADGE_SLOT,
          "정상 판매자를 정확히 알아본 증표.", effect_key="honest_spotter"),

    # ---------- 미션 훈련 배지 (돌발 퀘스트 완료 증표) ----------
    _item("badge_delivery_survivor", "배송거래 생존자 배지", "badge", "rare", BADGE_SLOT,
          "직거래가 어려운 상황에서도 택배거래를 안전하게 마친 증표.",
          effect_key="mission_delivery_survivor"),
    _item("badge_safe_payment_pro", "플랫폼 안전결제 숙련자 배지", "badge", "rare", BADGE_SLOT,
          "외부 결제 없이 플랫폼 안전결제만으로 거래를 마친 증표.",
          effect_key="mission_safe_payment_pro"),
    _item("badge_boundary_keeper", "경계 지킴이 배지", "badge", "rare", BADGE_SLOT,
          "사적 연락 요구를 플랫폼 안에서 끝까지 거절한 증표.",
          effect_key="mission_boundary_keeper"),
    _item("badge_evidence_first", "증거 중심 대응 배지", "badge", "rare", BADGE_SLOT,
          "감정 대신 기록과 증거로 침착하게 대응한 증표.",
          effect_key="mission_evidence_first"),
    _item("badge_manner_blocker", "비매너 차단 배지", "badge", "rare", BADGE_SLOT,
          "과도한 요구에도 기준선을 지키고 비매너를 차단한 증표.",
          effect_key="mission_manner_blocker"),

    # ---------- 거래 도구 (체크리스트/힌트/답변칩) ----------
    _item("tool_price_radar", "시세 레이더", "tool", "uncommon", "tool",
          "구매 시 시세 대비 가격이 수상하면 카드에 주의 신호를 띄운다.",
          effect_key="price_radar"),
    _item("tool_link_warning", "링크 경고기", "tool", "uncommon", "tool",
          "상대가 외부 링크를 보내면 경고 아이콘을 표시한다.",
          effect_key="link_warning"),
    _item("tool_account_note", "계좌 명의 체크 노트", "tool", "rare", "tool",
          "계좌 명의 일치 확인을 잊지 않게 도와주는 노트.",
          effect_key="account_check"),
    _item("tool_proof_kit", "사진 인증 키트", "tool", "uncommon", "tool",
          "실물/구성품 사진을 요청하는 빠른 답변칩을 제공한다.",
          effect_key="proof_request_kit"),
    _item("tool_evidence_folder", "거래 기록 폴더", "tool", "rare", "tool",
          "판매 전 상태 사진/대화 기록을 근거로 답하도록 일깨워준다.",
          effect_key="evidence_folder"),
    _item("tool_refund_card", "환불 대응 카드", "tool", "rare", "tool",
          "침착한 거절/부분환불/플랫폼 분쟁 답변 템플릿을 제공한다(일반 정보, 법률 자문 아님).",
          effect_key="refund_response_card"),
    _item("tool_safe_checklist", "직거래 안전 체크리스트", "tool", "common", "tool",
          "거래 체크리스트를 자동으로 펼쳐 보여준다.",
          effect_key="safe_trade_checklist"),
    _item("tool_dispute_guide", "플랫폼 분쟁 가이드", "tool", "epic", "tool",
          "플랫폼 분쟁 절차 안내 답변칩을 제공한다(일반 정보, 법률 자문 아님).",
          effect_key="dispute_guide"),
]

ITEMS_BY_ID = {it["id"]: it for it in ITEM_DEFS}


def seed_default_items(conn: sqlite3.Connection) -> None:
    """기본 아이템을 안전한 UPSERT 로 시드한다 (기존 보유/장착 기록 보존)."""
    now = _now()
    for it in ITEM_DEFS:
        conn.execute(
            """
            INSERT INTO items (id, name, item_type, rarity, slot, description,
                               effect_key, visual_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, item_type = excluded.item_type,
                rarity = excluded.rarity, slot = excluded.slot,
                description = excluded.description, effect_key = excluded.effect_key,
                visual_json = excluded.visual_json
            """,
            (it["id"], it["name"], it["item_type"], it["rarity"], it["slot"],
             it["description"], it["effect_key"],
             json.dumps(it["visual"], ensure_ascii=False), now),
        )


# ============================================================
#  지급 / 보유 / 장착
# ============================================================
def grant_item(conn: sqlite3.Connection, user_id: int, item_id: str) -> bool:
    """아이템 지급. 이미 있으면 수량 +1. 정의에 없는 id 는 무시."""
    if item_id not in ITEMS_BY_ID:
        return False
    conn.execute(
        """
        INSERT INTO user_items (user_id, item_id, quantity, acquired_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, item_id) DO UPDATE SET
            quantity = quantity + 1,
            acquired_at = excluded.acquired_at
        """,
        (user_id, item_id, _now()),
    )
    return True


def _public_item(it: dict, quantity=1, equipped=False, equipped_slot=None) -> dict:
    return {
        "id": it["id"], "name": it["name"], "item_type": it["item_type"],
        "rarity": it["rarity"], "slot": it["slot"], "description": it["description"],
        "effect_key": it["effect_key"], "visual": it["visual"],
        "quantity": quantity, "equipped": equipped, "equipped_slot": equipped_slot,
    }


def _equipment_map(conn, user_id) -> dict:
    rows = conn.execute(
        "SELECT slot, item_id FROM user_equipment WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {r["slot"]: r["item_id"] for r in rows}


def list_inventory(conn: sqlite3.Connection, user_id: int) -> dict:
    """보유 아이템 + 장착 상태."""
    owned = conn.execute(
        "SELECT item_id, quantity FROM user_items WHERE user_id = ?", (user_id,)
    ).fetchall()
    equip = _equipment_map(conn, user_id)
    equipped_ids = set(equip.values())
    items = []
    for row in owned:
        it = ITEMS_BY_ID.get(row["item_id"])
        if not it:
            continue
        eq_slot = next((s for s, iid in equip.items() if iid == it["id"]), None)
        items.append(_public_item(it, row["quantity"], it["id"] in equipped_ids, eq_slot))
    # 희귀도/타입 정렬
    items.sort(key=lambda x: (x["item_type"], RARITY_ORDER.index(x["rarity"]) if x["rarity"] in RARITY_ORDER else 0))
    return {
        "items": items,
        "equipment": equip,
        "tool_slots": sorted(TOOL_SLOTS),
    }


def _resolve_slot(item: dict, requested: str | None, equip: dict) -> str | None:
    """아이템을 어느 슬롯에 끼울지 결정한다."""
    if item["item_type"] == "tool":
        if requested in TOOL_SLOTS:
            return requested
        # 비어있는 도구 슬롯 우선, 없으면 tool_1
        for s in sorted(TOOL_SLOTS):
            if s not in equip:
                return s
        return "tool_1"
    # 코스튬/배지/프레임: 정의된 슬롯 고정
    return item["slot"] if item["slot"] in ALL_SLOTS else None


def equip_item(conn: sqlite3.Connection, user_id: int, item_id: str,
               slot: str | None = None) -> dict:
    """아이템 장착. 같은 아이템이 다른 슬롯에 있으면 옮긴다. 반환: 인벤토리 상태."""
    it = ITEMS_BY_ID.get(item_id)
    if not it:
        raise ValueError("알 수 없는 아이템입니다.")
    owned = conn.execute(
        "SELECT 1 FROM user_items WHERE user_id = ? AND item_id = ? AND quantity > 0",
        (user_id, item_id),
    ).fetchone()
    if not owned:
        raise ValueError("보유하지 않은 아이템입니다.")
    equip = _equipment_map(conn, user_id)
    target = _resolve_slot(it, slot, equip)
    if not target:
        raise ValueError("장착할 수 없는 아이템입니다.")
    # 같은 아이템이 이미 다른 슬롯에 있으면 제거 (중복 장착 방지)
    conn.execute(
        "DELETE FROM user_equipment WHERE user_id = ? AND item_id = ?", (user_id, item_id)
    )
    conn.execute(
        """
        INSERT INTO user_equipment (user_id, slot, item_id, equipped_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, slot) DO UPDATE SET item_id = excluded.item_id,
                                                 equipped_at = excluded.equipped_at
        """,
        (user_id, target, item_id, _now()),
    )
    return list_inventory(conn, user_id)


def unequip_slot(conn: sqlite3.Connection, user_id: int, slot: str) -> dict:
    conn.execute(
        "DELETE FROM user_equipment WHERE user_id = ? AND slot = ?", (user_id, slot)
    )
    return list_inventory(conn, user_id)


# ============================================================
#  장착 효과 (대화/카드/아바타에 반영)
# ============================================================
def equipped_effects(conn: sqlite3.Connection, user_id: int) -> set[str]:
    """장착된 도구/배지의 effect_key 집합."""
    equip = _equipment_map(conn, user_id)
    out = set()
    for item_id in equip.values():
        it = ITEMS_BY_ID.get(item_id)
        if it and it.get("effect_key"):
            out.add(it["effect_key"])
    return out


def equipped_cosmetic_overrides(conn: sqlite3.Connection, user_id: int) -> dict:
    """장착된 코스튬의 아바타 오버라이드 (hat/shirt/...)."""
    equip = _equipment_map(conn, user_id)
    overrides: dict = {}
    for item_id in equip.values():
        it = ITEMS_BY_ID.get(item_id)
        if it and it["item_type"] == "cosmetic":
            overrides.update((it.get("visual") or {}).get("avatar", {}))
    return overrides


def equipped_badges(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """장착된 배지 목록 (대화 영향용)."""
    equip = _equipment_map(conn, user_id)
    badge_id = equip.get(BADGE_SLOT)
    it = ITEMS_BY_ID.get(badge_id) if badge_id else None
    return [{"effect_key": it["effect_key"], "name": it["name"]}] if it else []


# ============================================================
#  보상 굴리기 (성과/난이도/판정 기반)
# ============================================================
_BY_RARITY = {}
for _it in ITEM_DEFS:
    _BY_RARITY.setdefault(_it["rarity"], []).append(_it["id"])

# 좋은(올바른) 판정으로 간주되는 verdict — 보상은 안전한 행동을 장려한다.
_GOOD_VERDICTS = {
    "good_catch", "safe", "fair_sale", "handled_refund_villain",
    "handled_lowballer", "handled_risky", "ok_walkaway",
}


def _rarity_for(score: int, difficulty: str, correct: bool, rng: random.Random) -> str | None:
    """성과 → 희귀도. 틀린 결정엔 보상 없음(소소한 위로도 없음 — 안전행동 장려)."""
    if not correct:
        return None
    hard = (difficulty or "medium") == "hard"
    if score >= 98 and hard and rng.random() < 0.18:
        return "legendary"
    if score >= 92 and hard:
        return "epic"
    if score >= 90 or (score >= 82 and hard):
        return "rare"
    if score >= 72:
        return "uncommon"
    if rng.random() < 0.6:
        return "common"
    return None


def roll_item_rewards(score: int, difficulty: str, role: str, verdict: str,
                      correct: bool, rng: random.Random | None = None) -> list[str]:
    """지급할 아이템 id 목록 (보통 0~1개)."""
    rng = rng or random.Random()
    if verdict not in _GOOD_VERDICTS and not correct:
        return []
    rarity = _rarity_for(score, difficulty, correct, rng)
    if not rarity:
        return []
    pool = _BY_RARITY.get(rarity) or []
    if not pool:
        # 희귀도 풀이 비면 한 단계 낮춰서 시도
        for r in reversed(RARITY_ORDER[:RARITY_ORDER.index(rarity)]):
            if _BY_RARITY.get(r):
                pool = _BY_RARITY[r]
                break
    return [rng.choice(pool)] if pool else []


def calculate_trade_rewards(conn: sqlite3.Connection, user: sqlite3.Row, result: dict,
                            difficulty: str, role: str) -> list[dict]:
    """
    거래 결과로 아이템을 굴려 지급하고, 화면에 보여줄 '공개 아이템 정보'를 돌려준다.
    중복 보유는 수량으로 누적된다. 정답지(role 등)는 반환에 포함하지 않는다.
    """
    rng = random.Random()
    ids = roll_item_rewards(
        result.get("score", 0), difficulty, role,
        result.get("verdict", ""), bool(result.get("correct")), rng,
    )
    granted = []
    for item_id in ids:
        if grant_item(conn, user["id"], item_id):
            it = ITEMS_BY_ID[item_id]
            granted.append({
                "id": it["id"], "name": it["name"], "item_type": it["item_type"],
                "rarity": it["rarity"], "slot": it["slot"],
                "description": it["description"], "effect_key": it["effect_key"],
            })
    return granted
