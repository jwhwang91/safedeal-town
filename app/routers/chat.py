"""
채팅 라우터: NPC 와의 거래(대화) 한 판 전체 흐름.

  start    -> 거래 세션 생성, NPC 첫 인사
  message  -> 플레이어 한 마디 → NPC(역할극 에이전트) 답장
  flag     -> NPC 메시지를 '의심됨 🚩' 표시 / 해제
  resolve  -> 거래 종료 → 심판 에이전트 채점 → 보상 반영

모드는 '상대 NPC 의 종류'로 자동 결정된다:
  - 판매자 NPC(npc_kind='seller') → 구매자 모드 (SellerAgent + JudgeAgent.evaluate)
  - 구매자 NPC(npc_kind='buyer')  → 판매자 모드 (BuyerAgent + JudgeAgent.evaluate_seller_mode)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app import aftermath as aftermath_mod
from app import preferences as prefs_mgr
from app import rewards as rewards_mgr
from app import spawns as spawn_mgr
from app.ai import persona_factory
from app.ai.judge_agent import JudgeAgent
from app.ai.personas import BUYER_BEHAVIORS, SELLER_MODE_DISCLAIMER, TACTICS
from app.ai.roleplay import BuyerAgent, SellerAgent
from app.database import db_dependency
from app.deps import get_current_user
from app.models import (
    FlagMessageRequest,
    ResolveTradeRequest,
    SendMessageRequest,
    StartChatRequest,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 한 판 최대 플레이어 발화 수 (대화가 무한정 길어지지 않게)
_MAX_PLAYER_TURNS = 14

_BUYER_DECISIONS = {"buy", "walk_away", "report"}
_SELLER_DECISIONS = {
    "complete_sale", "refuse_refund", "accept_refund",
    "partial_refund", "escalate_platform", "cancel_trade",
}

# 판매자 모드 카테고리 → 한국어 라벨 (매물 표시용)
_CAT_LABEL = {
    "electronics": "전자제품", "camping": "캠핑용품", "beauty": "뷰티/화장품",
    "home": "생활용품", "fashion": "패션", "books": "도서", "general": "중고 물품",
}

# 거래 체크리스트 유효 키 (프론트 checklist.js 와 공유). 자기보고식이라 가점은 소폭·상한.
_BUYER_CHECKLIST_KEYS = {
    "price_check", "condition_check", "proof_request", "safe_method",
    "account_match", "refuse_link", "keep_in_platform",
}
_SELLER_CHECKLIST_KEYS = {
    "disclose_condition", "keep_evidence", "disclose_accessories", "clear_terms",
    "keep_in_platform", "stay_calm", "organize_evidence",
}
_CHECKLIST_BONUS_CAP = 4


def _checklist_bonus(checklist, valid_keys, correct: bool):
    """올바른 결정일 때만, '서로 다른' 유효 체크 항목 수만큼 소폭 가점(상한 _CHECKLIST_BONUS_CAP).

    중복 키로 점수를 부풀리지 못하도록 set 으로 중복을 제거한다.
    """
    valid = sorted({k for k in (checklist or []) if k in valid_keys})
    bonus = min(_CHECKLIST_BONUS_CAP, len(valid)) if correct else 0
    return bonus, valid


# 구매자 유형 → 종료 후 공개 라벨
_BUYER_TYPE_LABEL = {
    "honest_buyer": "정상 구매자",
    "refund_villain": "환불 빌런",
    "lowballer": "막깎이 구매자",
    "ghosting_buyer": "잠수러",
    "risky_buyer": "위험거래 유도형",
    "legit_claim_buyer": "정당한 하자 주장 구매자",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
#  재화(코인) + 아이템 경제
# ============================================================
# 어려운 상대일수록 보상이 크다 → 레벨이 오르며 등장하는 고난도 상대에 도전할 동기.
_DIFF_REWARD = {"easy": 20, "medium": 35, "hard": 55}


def _economy_delta(mode: str, verdict: str, correct: bool, npc: dict):
    """거래 결과 → (coin_delta, 획득아이템명|None, 아이템상실여부)."""
    reward = _DIFF_REWARD.get((npc.get("difficulty") or "medium"), 35)
    if mode == "buyer":
        if verdict == "safe":          # 정상 판매자에게 구매 성공 → 물건 획득 + 코인
            return reward, npc["item_name"], False
        if verdict == "good_catch":    # 사기 회피 → 돈을 지킴(코인)
            return round(reward * 0.7), None, False
        if verdict == "scammed":       # 사기당함 → 코인 잃고 모은 아이템 하나 뺏김
            return -reward, None, True
        return 5, None, False          # missed_deal — 정상 거래를 놓침(소소)
    # ---- 판매자 모드 ----
    if verdict == "over_refunded":     # 괜한 환불 → 손해 + 아이템 뺏김
        return -reward, None, True
    if verdict == "unsafe_response":   # 위험/욕설 대응 → 손해
        return -round(reward * 0.6), None, False
    if correct:                        # 환불 없이 잘 팔거나 빌런 방어 → 코인
        return reward, None, False
    return 3, None, False              # lost_sale / missed_legitimate_claim 등


def _resolve_economy(user: sqlite3.Row, coin_delta: int, gain_item, lose_item: bool) -> dict:
    """현재 코인/인벤토리에 변화를 적용한 결과를 계산한다 (DB 쓰기는 _persist 가 한다)."""
    keys = user.keys()
    coins_before = user["coins"] if ("coins" in keys and user["coins"] is not None) else 0
    inv: list = []
    raw = user["inventory_json"] if "inventory_json" in keys else None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                inv = [str(x) for x in parsed]
        except (json.JSONDecodeError, TypeError):
            inv = []
    lost_name = inv.pop() if (lose_item and inv) else None  # 최근에 모은 아이템을 뺏긴다
    gained_name = None
    if gain_item:
        inv.append(str(gain_item))
        gained_name = str(gain_item)
    inv = inv[-50:]  # 인벤토리 상한
    coins_after = max(0, coins_before + coin_delta)
    return {
        "coin_delta": coins_after - coins_before,  # 0 밑으로는 안 깎이므로 실제 변화량
        "coins_after": coins_after,
        "item_gained": gained_name,
        "item_lost": lost_name,
        "inventory": inv,
        "item_count": len(inv),
    }


def _load_npc(conn: sqlite3.Connection, npc_id: str) -> dict:
    """DB 의 npc row 를 personas 형식의 dict 로 복원 (정적 NPC 폴백)."""
    row = conn.execute("SELECT * FROM npcs WHERE id = ?", (npc_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="NPC를 찾을 수 없습니다.")
    npc = dict(row)
    npc["persona"] = json.loads(npc["persona_json"])
    npc["tactics"] = json.loads(npc["tactics_json"])
    from app.ai.personas import npc_by_id

    src = npc_by_id(npc_id)
    if src:
        npc["mock_lines"] = src.get("mock_lines", {})
    return npc


def _coerce_dynamic_npc(data: dict) -> dict:
    """세션/스폰에 저장된 동적 NPC dict 를 에이전트가 쓰는 형태로 보정.

    JSON 이 (DB 손상/구버전 등으로) 일부 필드가 비어 있어도 에이전트/프롬프트가
    KeyError 로 죽지 않도록, 접근되는 모든 필드에 안전한 기본값을 채운다.
    """
    data.setdefault("npc_kind", "seller")
    data.setdefault("role", "honest")
    data.setdefault("difficulty", "medium")
    data.setdefault("name", "익명")
    data.setdefault("item_name", "중고 물품")
    data.setdefault("item_category", "중고 물품")
    data.setdefault("listing_price", 0)
    data.setdefault("market_price", 0)
    data.setdefault("location", "동네 직거래")
    data.setdefault("sprite_color", "#b0a080")
    data.setdefault("tactics", [])
    data.setdefault("mock_lines", {})
    persona = data.get("persona")
    if not isinstance(persona, dict):
        persona = {}
    persona.setdefault("appearance", "")
    persona.setdefault("personality", "평범한 성격")
    persona.setdefault("speech_style", "평범한 채팅체")
    persona.setdefault("backstory", "")
    persona.setdefault("opening_line", "안녕하세요, 문의 주셔서 감사합니다.")
    data["persona"] = persona
    return data


def _npc_from_session(conn: sqlite3.Connection, sess: sqlite3.Row) -> dict:
    """이 거래의 NPC. 동적 NPC(session_npc_json)가 있으면 그걸, 없으면 npcs 테이블."""
    raw = sess["session_npc_json"] if "session_npc_json" in sess.keys() else None
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return _coerce_dynamic_npc(data)
        except (json.JSONDecodeError, TypeError):
            pass
    return _load_npc(conn, sess["npc_id"])


def _load_session(conn: sqlite3.Connection, session_id: str, user_id: int) -> sqlite3.Row:
    sess = conn.execute(
        "SELECT * FROM trade_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    if not sess:
        raise HTTPException(status_code=404, detail="거래 세션을 찾을 수 없습니다.")
    return sess


def _load_history(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, turn_index, speaker, content, tactic, flagged_by_player "
        "FROM chat_messages WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _make_agent(npc: dict, user: sqlite3.Row, seller_listing: dict | None = None):
    """NPC 종류에 따라 알맞은 역할극 에이전트를 만든다."""
    if npc["npc_kind"] == "buyer":
        return BuyerAgent(npc, user["seller_category"], seller_listing)
    return SellerAgent(npc)


def _resolve_spawn(conn: sqlite3.Connection, user_id: int, body: StartChatRequest):
    """
    클라이언트는 spawn_instance_id 만 보낸다 → 서버가 (npc_id, dynamic_json) 을 찾는다.
    (role 을 노출하는 npc_id 를 클라이언트가 알 필요가 없도록 분리.)
    npc_id 직접 지정은 디버그용 폴백.
    """
    if body.spawn_instance_id:
        row = conn.execute(
            "SELECT npc_id, dynamic_json FROM active_spawns WHERE id = ? AND user_id = ?",
            (body.spawn_instance_id, user_id),
        ).fetchone()
        if row:
            return row["npc_id"], row["dynamic_json"]
    if body.npc_id:
        return body.npc_id, None
    raise HTTPException(status_code=404, detail="대화 상대를 찾을 수 없습니다. (스폰이 사라졌을 수 있어요)")


# ---------------------------------------------------------------
@router.post("/start")
def start_chat(
    body: StartChatRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    npc_id, dynamic_json = _resolve_spawn(conn, user["id"], body)
    npc, session_npc_json = None, None
    if dynamic_json:
        try:
            npc = _coerce_dynamic_npc(json.loads(dynamic_json))
            session_npc_json = dynamic_json
        except (json.JSONDecodeError, TypeError):
            npc = None  # 깨진 JSON → 정적 NPC 로 폴백
    if npc is None:
        npc = _load_npc(conn, npc_id)
        session_npc_json = None
    mode = "seller" if npc["npc_kind"] == "buyer" else "buyer"
    seller_listing = prefs_mgr.get_seller_listing(conn, user["id"]) if mode == "seller" else None
    market_seed_json = (
        json.dumps(npc.get("listing"), ensure_ascii=False) if npc.get("listing") else None
    )

    session_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO trade_sessions (id, user_id, npc_id, status, game_role, "
        "counterparty_kind, scenario_type, spawn_instance_id, session_npc_json, "
        "market_seed_json, started_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)",
        (session_id, user["id"], npc["id"], mode, npc["npc_kind"],
         npc["role"], body.spawn_instance_id, session_npc_json, market_seed_json, _now()),
    )
    # 말 건 스폰은 활성 풀에서 빼서 거래 도중 사라지지 않게 한다
    spawn_mgr.engage(conn, user["id"], body.spawn_instance_id)

    agent = _make_agent(npc, user, seller_listing)
    opening = agent.opening()
    conn.execute(
        "INSERT INTO chat_messages (session_id, turn_index, speaker, content, tactic, created_at) "
        "VALUES (?, 0, 'npc', ?, ?, ?)",
        (session_id, opening["message"], opening["tactic"], _now()),
    )
    conn.commit()

    opening_row = conn.execute(
        "SELECT id FROM chat_messages WHERE session_id = ? AND turn_index = 0",
        (session_id,),
    ).fetchone()

    # 매물 표시: 판매자 모드면 '내 판매글', 구매자 모드면 NPC 매물
    if mode == "seller":
        if seller_listing:
            item_name = seller_listing.get("product_name", "내 매물")
            item_category = seller_listing.get("category_label", "중고 물품")
            listing_price = seller_listing.get("listing_price", 0)
            market_price = seller_listing.get("market_price", 0)
        else:
            cat = user["seller_category"] or "general"
            label = _CAT_LABEL.get(cat, "중고 물품")
            item_name = f"내 {label} 매물"
            item_category = label
            listing_price = 0
            market_price = 0
        location = "동네 직거래"
    else:
        item_name = npc["item_name"]
        item_category = npc["item_category"]
        listing_price = npc["listing_price"]
        market_price = npc["market_price"]
        location = npc["location"]

    return {
        "session_id": session_id,
        "mode": mode,
        "npc": {
            "name": npc["name"],
            "npc_kind": npc["npc_kind"],
            "item_name": item_name,
            "item_category": item_category,
            "listing_price": listing_price,
            "market_price": market_price,
            "location": location,
            "difficulty": npc["difficulty"],
            "sprite_color": npc["sprite_color"],
            # 정답지 보호: 구매자 NPC 의 실제 visual_theme/category 는 유형과 상관관계가 있어
            # 내려보내지 않는다 (프론트는 쓰지 않음). 마을 스폰은 _public_spawn 이 역할 무관 테마를 준다.
            "appearance": npc["persona"].get("appearance", ""),
        },
        "opening": {"message_id": opening_row["id"], "content": opening["message"]},
        "max_turns": _MAX_PLAYER_TURNS,
    }


# ---------------------------------------------------------------
@router.post("/card")
def npc_card(
    body: StartChatRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """대화 시작 전에 보여줄 공개 프로필/매물 카드. 정답지(role/tactic)는 절대 미포함."""
    npc_id, dynamic_json = _resolve_spawn(conn, user["id"], body)
    npc = None
    if dynamic_json:
        try:
            npc = _coerce_dynamic_npc(json.loads(dynamic_json))
        except (json.JSONDecodeError, TypeError):
            npc = None
    if npc is None:
        npc = _load_npc(conn, npc_id)
    mode = "seller" if npc["npc_kind"] == "buyer" else "buyer"
    seller_listing = prefs_mgr.get_seller_listing(conn, user["id"]) if mode == "seller" else None
    spawn_key = body.spawn_instance_id or npc_id
    card = persona_factory.build_profile_card(npc, mode, spawn_key, seller_listing)

    # 시세 레이더(도구): 구매 시 시세 대비 가격이 수상하면 '주의' 힌트만 준다(정답 아님).
    effects = rewards_mgr.equipped_effects(conn, user["id"])
    if mode == "buyer" and "price_radar" in effects:
        L = card.get("listing", {})
        price, market = L.get("listing_price") or 0, L.get("market_price") or 0
        if market > 0 and price > 0:
            ratio = price / market
            if ratio <= 0.7:
                card["price_radar"] = "시세 대비 매우 낮은 가격일 수 있어요. 왜 싼지 꼭 확인하세요."
            elif ratio <= 0.85:
                card["price_radar"] = "시세보다 다소 낮아요. 상태·이유를 확인해 보세요."
    return card


# ---------------------------------------------------------------
@router.post("/message")
def send_message(
    body: SendMessageRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    sess = _load_session(conn, body.session_id, user["id"])
    if sess["status"] != "active":
        raise HTTPException(status_code=400, detail="이미 끝난 거래입니다.")

    history = _load_history(conn, body.session_id)
    player_turns = sum(1 for m in history if m["speaker"] == "player")
    if player_turns >= _MAX_PLAYER_TURNS:
        raise HTTPException(
            status_code=400,
            detail="대화가 너무 길어졌어요. 이제 거래를 마무리해 주세요.",
        )

    next_turn = len(history)
    conn.execute(
        "INSERT INTO chat_messages (session_id, turn_index, speaker, content, created_at) "
        "VALUES (?, ?, 'player', ?, ?)",
        (body.session_id, next_turn, body.message.strip(), _now()),
    )

    npc = _npc_from_session(conn, sess)
    seller_listing = (
        prefs_mgr.get_seller_listing(conn, user["id"]) if npc["npc_kind"] == "buyer" else None
    )
    agent = _make_agent(npc, user, seller_listing)
    updated_history = _load_history(conn, body.session_id)
    reply = agent.reply(updated_history)

    conn.execute(
        "INSERT INTO chat_messages (session_id, turn_index, speaker, content, tactic, created_at) "
        "VALUES (?, ?, 'npc', ?, ?, ?)",
        (body.session_id, next_turn + 1, reply["message"], reply["tactic"], _now()),
    )
    conn.commit()

    npc_row = conn.execute(
        "SELECT id FROM chat_messages WHERE session_id = ? AND turn_index = ?",
        (body.session_id, next_turn + 1),
    ).fetchone()

    return {
        "reply": {"message_id": npc_row["id"], "content": reply["message"]},
        "player_turns_used": player_turns + 1,
        "max_turns": _MAX_PLAYER_TURNS,
    }


# ---------------------------------------------------------------
@router.post("/flag")
def flag_message(
    body: FlagMessageRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    _load_session(conn, body.session_id, user["id"])
    row = conn.execute(
        "SELECT speaker FROM chat_messages WHERE id = ? AND session_id = ?",
        (body.message_id, body.session_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="메시지를 찾을 수 없습니다.")
    if row["speaker"] != "npc":
        raise HTTPException(status_code=400, detail="상대방 메시지만 의심 표시할 수 있어요.")

    conn.execute(
        "UPDATE chat_messages SET flagged_by_player = ? WHERE id = ?",
        (1 if body.flagged else 0, body.message_id),
    )
    conn.commit()
    return {"message_id": body.message_id, "flagged": body.flagged}


# ---------------------------------------------------------------
@router.post("/resolve")
def resolve_trade(
    body: ResolveTradeRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    sess = _load_session(conn, body.session_id, user["id"])
    if sess["status"] != "active":
        raise HTTPException(status_code=400, detail="이미 끝난 거래입니다.")

    npc = _npc_from_session(conn, sess)
    transcript = _load_history(conn, body.session_id)
    mode = sess["game_role"] or ("seller" if npc["npc_kind"] == "buyer" else "buyer")

    if mode == "seller":
        return _resolve_seller_mode(conn, user, sess, npc, transcript, body.decision, body.checklist)
    return _resolve_buyer_mode(conn, user, sess, npc, transcript, body.decision, body.checklist)


# ---------------------------------------------------------------
def _resolve_buyer_mode(conn, user, sess, npc, transcript, decision, checklist=None) -> dict:
    if decision not in _BUYER_DECISIONS:
        raise HTTPException(status_code=400, detail="구매자 모드에서 쓸 수 없는 결정입니다.")

    judge = JudgeAgent()
    result = judge.evaluate(npc, transcript, decision)
    score, correct = result["score"], result["correct"]
    bonus, checked = _checklist_bonus(checklist, _BUYER_CHECKLIST_KEYS, correct)
    score = max(0, min(100, score + bonus))
    result["score"] = score  # 보상 굴리기/저장이 가점 반영된 점수를 쓰도록
    xp_delta = score if correct else max(5, score // 4)

    trust_delta = {
        "good_catch": 6, "safe": 4, "missed_deal": -3, "scammed": -15,
    }.get(result["verdict"], 0)

    coin_delta, gain_item, lose_item = _economy_delta("buyer", result["verdict"], correct, npc)
    econ = _resolve_economy(user, coin_delta, gain_item, lose_item)

    annotated = _annotate(transcript, TACTICS)
    reward_items = rewards_mgr.calculate_trade_rewards(
        conn, user, result, npc.get("difficulty", "medium"), npc.get("role", "")
    )
    extras = {
        "counterparty_name": npc.get("name"),
        "item_name": npc.get("item_name"),
        "reward_items_json": json.dumps(reward_items, ensure_ascii=False) if reward_items else None,
        "checklist_json": json.dumps(checked, ensure_ascii=False) if checked else None,
    }
    _persist(conn, user, sess, npc, "buyer", result, score, correct,
             xp_delta, trust_delta, decision, econ, extras)

    return {
        "mode": "buyer",
        "verdict": result["verdict"],
        "correct": correct,
        "score": score,
        "decision": decision,
        "npc_role": npc["role"],
        "detected_flags": result["detected_flags"],
        "missed_flags": result["missed_flags"],
        "coaching": result["coaching"],
        "rewards": _rewards(user, xp_delta, trust_delta, econ),
        "reward_items": reward_items,
        "checklist": checked,
        "checklist_bonus": bonus,
        "aftermath": aftermath_mod.aftermath_for(result["verdict"]),
        "annotated_transcript": annotated,
    }


def _resolve_seller_mode(conn, user, sess, npc, transcript, decision, checklist=None) -> dict:
    if decision not in _SELLER_DECISIONS:
        raise HTTPException(status_code=400, detail="판매자 모드에서 쓸 수 없는 결정입니다.")

    judge = JudgeAgent()
    result = judge.evaluate_seller_mode(npc, transcript, decision)
    score, correct = result["score"], result["correct"]
    bonus, checked = _checklist_bonus(checklist, _SELLER_CHECKLIST_KEYS, correct)
    score = max(0, min(100, score + bonus))
    result["score"] = score  # 보상 굴리기/저장이 가점 반영된 점수를 쓰도록
    xp_delta = score if correct else max(5, score // 4)

    trust_delta = {
        "fair_sale": 4, "handled_refund_villain": 6, "handled_lowballer": 5,
        "handled_risky": 6, "ok_walkaway": 3,
        "over_refunded": -6, "unsafe_response": -10, "lost_sale": -3,
        "missed_legitimate_claim": -6,
    }.get(result["verdict"], 0)

    coin_delta, gain_item, lose_item = _economy_delta("seller", result["verdict"], correct, npc)
    econ = _resolve_economy(user, coin_delta, gain_item, lose_item)

    annotated = _annotate(transcript, BUYER_BEHAVIORS)
    sl = prefs_mgr.get_seller_listing(conn, user["id"])
    reward_items = rewards_mgr.calculate_trade_rewards(
        conn, user, result, npc.get("difficulty", "medium"), npc.get("role", "")
    )
    extras = {
        "counterparty_name": npc.get("name"),
        "item_name": (sl or {}).get("product_name") or "내 매물",
        "reward_items_json": json.dumps(reward_items, ensure_ascii=False) if reward_items else None,
        "checklist_json": json.dumps(checked, ensure_ascii=False) if checked else None,
    }
    _persist(conn, user, sess, npc, "seller", result, score, correct,
             xp_delta, trust_delta, decision, econ, extras)

    return {
        "mode": "seller",
        "verdict": result["verdict"],
        "correct": correct,
        "score": score,
        "decision": decision,
        "npc_role": npc["role"],
        "counterparty_label": _BUYER_TYPE_LABEL.get(npc["role"], "구매자"),
        "detected_flags": result["detected_flags"],
        "missed_flags": result["missed_flags"],
        "coaching": result["coaching"],
        "disclaimer": SELLER_MODE_DISCLAIMER,
        "rewards": _rewards(user, xp_delta, trust_delta, econ),
        "reward_items": reward_items,
        "checklist": checked,
        "checklist_bonus": bonus,
        "aftermath": aftermath_mod.aftermath_for(result["verdict"]),
        "annotated_transcript": annotated,
    }


# ---------------------------------------------------------------
def _annotate(transcript: list[dict], catalog: dict) -> list[dict]:
    """종료 후 정답(수법/행동 주석) 공개. catalog 는 TACTICS 또는 BUYER_BEHAVIORS."""
    annotated = []
    for m in transcript:
        item = {
            "speaker": m["speaker"],
            "content": m["content"],
            "flagged_by_player": bool(m["flagged_by_player"]),
            "tactic": None,
        }
        if m["speaker"] == "npc" and m["tactic"] and m["tactic"] != "none":
            t = catalog.get(m["tactic"], {})
            item["tactic"] = {
                "id": m["tactic"],
                "label": t.get("label", m["tactic"]),
                "red_flag": t.get("red_flag", ""),
                "counter": t.get("counter", ""),
            }
        annotated.append(item)
    return annotated


def _rewards(user, xp_delta, trust_delta, econ) -> dict:
    new_xp = user["xp"] + xp_delta
    new_level = 1 + new_xp // 100
    new_trust = max(0, min(100, user["trust_score"] + trust_delta))
    return {
        "xp_delta": xp_delta,
        "trust_delta": trust_delta,
        "new_xp": new_xp,
        "new_level": new_level,
        "new_trust": new_trust,
        "leveled_up": new_level > user["level"],
        "coin_delta": econ["coin_delta"],
        "new_coins": econ["coins_after"],
        "item_gained": econ["item_gained"],
        "item_lost": econ["item_lost"],
        "item_count": econ["item_count"],
    }


def _persist(conn, user, sess, npc, mode, result, score, correct, xp_delta,
             trust_delta, decision, econ, extras=None) -> None:
    now = _now()
    extras = extras or {}
    conn.execute(
        """
        INSERT OR REPLACE INTO trade_results
            (session_id, user_id, npc_id, game_role, verdict, correct, score,
             detected_flags_json, missed_flags_json, coaching, xp_delta,
             counterparty_name, item_name, checklist_json, reward_items_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sess["id"], user["id"], npc["id"], mode,
            result["verdict"], 1 if correct else 0, score,
            json.dumps(result["detected_flags"], ensure_ascii=False),
            json.dumps(result["missed_flags"], ensure_ascii=False),
            result["coaching"], xp_delta,
            extras.get("counterparty_name"), extras.get("item_name"),
            extras.get("checklist_json"), extras.get("reward_items_json"), now,
        ),
    )
    conn.execute(
        "UPDATE trade_sessions SET status = 'resolved', player_decision = ?, ended_at = ? WHERE id = ?",
        (decision, now, sess["id"]),
    )

    prog = conn.execute(
        "SELECT attempts, best_score, cleared FROM player_npc_progress WHERE user_id = ? AND npc_id = ?",
        (user["id"], npc["id"]),
    ).fetchone()
    if prog:
        conn.execute(
            "UPDATE player_npc_progress SET attempts = ?, best_score = ?, cleared = ?, last_played_at = ? "
            "WHERE user_id = ? AND npc_id = ?",
            (prog["attempts"] + 1, max(prog["best_score"], score),
             1 if (prog["cleared"] or correct) else 0, now, user["id"], npc["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO player_npc_progress (user_id, npc_id, attempts, best_score, cleared, last_played_at) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (user["id"], npc["id"], score, 1 if correct else 0, now),
        )

    rw = _rewards(user, xp_delta, trust_delta, econ)
    conn.execute(
        "UPDATE users SET xp = ?, level = ?, trust_score = ?, coins = ?, "
        "inventory_json = ?, updated_at = ? WHERE id = ?",
        (rw["new_xp"], rw["new_level"], rw["new_trust"], econ["coins_after"],
         json.dumps(econ["inventory"], ensure_ascii=False), now, user["id"]),
    )
    conn.commit()
