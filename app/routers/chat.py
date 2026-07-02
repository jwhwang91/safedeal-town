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
from fastapi.responses import FileResponse

from app import aftermath as aftermath_mod
from app import missions as missions_mgr
from app import portraits as portrait_mgr
from app import preferences as prefs_mgr
from app import rewards as rewards_mgr
from app import spawns as spawn_mgr
from app.ai import adaptive_memory, adaptive_repository, adaptive_selector, persona_variant
from app.ai import image_gen
from app.ai import pattern_taxonomy as taxonomy
from app.ai import persona_factory
from app.ai.judge_agent import JudgeAgent
from app.ai.personas import BUYER_BEHAVIORS, SELLER_MODE_DISCLAIMER, TACTICS
from app.ai.roleplay import BuyerAgent, SellerAgent
from app.config import get_settings
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

# 구매자 모드 빠른 문의 칩.
# 실제 중고앱처럼 '구매자(플레이어)가 먼저' 판매자에게 문의를 보낸다.
# 판매자 NPC 는 절대 먼저 말하지 않는다 (정답지 노출 없는 중립 문구).
_BUYER_SUGGESTED_MESSAGES = [
    "아직 판매 중인가요?",
    "직거래 가능할까요?",
    "상태 사진 더 볼 수 있을까요?",
    "네고 가능할까요?",
    "구성품은 전부 있나요?",
]

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
    # 방어 훈련 위험 구매자 계열
    "private_contact_buyer": "사적 연락 요구형",
    "romantic_pressure_buyer": "로맨틱 경계 침해형",
    "voice_phishing_buyer": "외부 인증 유도형",
    "social_engineering_buyer": "감정·긴박 압박형",
    "harasser_buyer": "거절 후 공격형",
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
    if verdict == "player_misconduct":  # 플레이어 본인 부적절 행위 → 손해(양쪽 모드)
        return -round(reward * 0.6), None, False
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
        "SELECT id, turn_index, speaker, content, tactic, flagged_by_player, image_data_uri "
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
    판매자 모드 인바운드 문의에서 시작하면 inquiry_id 만 온다 → 서버가 스폰으로 매핑한다.
    npc_id 직접 지정은 디버그용 폴백.
    """
    # 인바운드 문의 → 스폰 매핑 (본인 소유 + 대기 중 + 스폰 생존일 때만). 정답지 보호 유지.
    if body.inquiry_id:
        from app import inquiries as inquiry_mgr
        spawn_id = inquiry_mgr.spawn_id_for(conn, user_id, body.inquiry_id)
        if spawn_id:
            row = conn.execute(
                "SELECT npc_id, dynamic_json FROM active_spawns WHERE id = ? AND user_id = ?",
                (spawn_id, user_id),
            ).fetchone()
            if row:
                # 이후 engage/세션기록이 같은 스폰을 가리키도록 채워준다.
                body.spawn_instance_id = spawn_id
                return row["npc_id"], row["dynamic_json"]
        raise HTTPException(
            status_code=404,
            detail="이미 떠났거나 만료된 문의예요. 다른 문의를 골라 주세요.",
        )
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
#  NPC 초상(얼굴) — 불투명 URL 로만 노출 (family/role/gender 비노출)
# ---------------------------------------------------------------
def _portrait_url(spawn_instance_id: str | None) -> str | None:
    """스폰 id 로 만든 불투명 초상 URL (<img src> 용). id 가 없으면 None.

    URL 에는 스폰 id(추측 불가 UUID)만 담긴다 → family/role/gender 가 새지 않는다.
    """
    if not spawn_instance_id:
        return None
    return f"/api/chat/portrait/{spawn_instance_id}"


def _resolve_role_for_portrait(
    conn: sqlite3.Connection, spawn_instance_id: str,
) -> tuple[str | None, list, str | None, str | None, str | None] | None:
    """스폰 id → (role, tactics, gender_presentation, category, portrait_asset_id). 공개 엔드포인트 전용.

    /card·/start 의 스폰→NPC 해석 로직을 재사용한다: 동적 NPC(dynamic_json)가 있으면
    그 정답지를, 없으면 npcs 테이블의 role/tactics 를 쓴다. 진행 중 거래로 스폰이
    이미 engaged/만료됐을 수 있어 trade_sessions 로도 폴백 조회한다.
    portrait_asset_id 가 있으면(생성 시 고정한 얼굴) 그 얼굴을 그대로 서빙한다 → 겉모습 설명과
    100% 일치. gender_presentation/category 는 asset 이 없을 때의 매칭 힌트일 뿐(정답 아님).
    """
    npc_id = None
    dynamic_json = None
    row = conn.execute(
        "SELECT npc_id, dynamic_json FROM active_spawns WHERE id = ?",
        (spawn_instance_id,),
    ).fetchone()
    if row:
        npc_id, dynamic_json = row["npc_id"], row["dynamic_json"]
    else:
        srow = conn.execute(
            "SELECT npc_id, session_npc_json FROM trade_sessions "
            "WHERE spawn_instance_id = ? ORDER BY started_at DESC LIMIT 1",
            (spawn_instance_id,),
        ).fetchone()
        if srow:
            npc_id, dynamic_json = srow["npc_id"], srow["session_npc_json"]

    if npc_id is None and not dynamic_json:
        return None

    if dynamic_json:  # 동적 NPC 정답지 우선
        try:
            data = json.loads(dynamic_json)
            if isinstance(data, dict):
                return (
                    data.get("role"),
                    (data.get("tactics") or []),
                    data.get("gender_presentation"),
                    data.get("category") or data.get("item_category"),
                    data.get("portrait_asset_id"),
                )
        except (json.JSONDecodeError, TypeError):
            pass

    if npc_id:  # 정적 NPC 폴백 (gender/asset 정보 없음 → 초상 리졸버가 seed 로 결정)
        nrow = conn.execute(
            "SELECT role, tactics_json, category FROM npcs WHERE id = ?", (npc_id,)
        ).fetchone()
        if nrow:
            try:
                tactics = json.loads(nrow["tactics_json"]) if nrow["tactics_json"] else []
            except (json.JSONDecodeError, TypeError):
                tactics = []
            # category 는 schema.sql + 시작 시 마이그레이션으로 항상 존재한다.
            return nrow["role"], tactics, None, nrow["category"], None
    return None


@router.get("/portrait/{spawn_instance_id}")
def npc_portrait(
    spawn_instance_id: str,
    conn: sqlite3.Connection = Depends(db_dependency),
) -> FileResponse:
    """스폰 NPC 의 초상 이미지(공개·인증 없음).

    <img> 태그로 로드되므로 Bearer 헤더를 실을 수 없어 공개로 둔다. 스폰 id 는 추측
    불가한 UUID 라 허용 가능하다. 정답지 보호: 응답 URL/헤더/파일명 어디에도
    family/role/gender 를 노출하지 않는다(filename 미지정 → Content-Disposition 자체가
    안 붙음). 스폰을 모르거나 이미지를 못 고르면 404(누출 없는 일반 메시지).
    """
    resolved = _resolve_role_for_portrait(conn, spawn_instance_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="Not found")
    role, tactics, gender_presentation, category, portrait_asset_id = resolved
    # 생성 시 고정한 얼굴이 있으면 그대로 서빙(겉모습 설명과 100% 일치). 없으면 seed 로 리졸브.
    path = portrait_mgr.path_for_asset_id(portrait_asset_id) or portrait_mgr.resolve_portrait_path(
        role, tactics, spawn_instance_id,
        gender_presentation=gender_presentation, category=category,
    )
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    # 확장자로 미디어 타입 추론(웹 최적화로 jpg/webp 로 서빙될 수 있음). filename 은 여전히 미지정.
    _suffix = path.suffix.lower()
    _media = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".png": "image/png",
    }.get(_suffix, "image/png")
    return FileResponse(path, media_type=_media)


# ---------------------------------------------------------------
def _apply_adaptive_start(conn, user, npc, mode, session_npc_json, seller_listing):
    """시작 시 적응형 선택 + 안전한 페르소나 변주를 적용한다.

    반환: (npc(변주 반영 가능), session_npc_json(변주 반영), adaptive_ctx|None)
    적응형 OFF 이거나 어떤 예외가 나도 기존 npc/세션 흐름을 그대로 돌려준다(게임 보존).
    숨은 선택 로직은 프론트로 절대 나가지 않는다 (서버 전용 컨텍스트로만 저장).
    """
    settings = get_settings()
    if not settings.adaptive_scenarios_enabled:
        return npc, session_npc_json, None
    try:
        counterparty_kind = taxonomy.counterparty_kind_for(npc)
        # 적응형 맥락의 '카테고리/매물': 모드에 맞는 진짜 값으로 넣는다.
        #  - 판매자 모드(구매자 NPC): 플레이어가 올린 판매글의 카테고리/매물
        #  - 구매자 모드(판매자 NPC): 그 NPC 매물의 카테고리/매물
        # 이렇게 해야 변주가 '사용자가 고른 카테고리/판매글 안에서만' 다양해지고,
        # 무관한 품목 카테고리로 새지 않는다.
        if mode == "seller":
            adaptive_category = (seller_listing or {}).get("canonical_category") \
                or (seller_listing or {}).get("category") or "general"
            adaptive_listing = seller_listing
        else:
            adaptive_category = npc.get("category")
            adaptive_listing = npc.get("listing")
        selection = adaptive_selector.select_adaptive_patterns(
            conn, user["id"], mode, counterparty_kind,
            category=adaptive_category, difficulty=npc.get("difficulty"), limit=2,
        )
        variant = persona_variant.build_persona_variant(
            npc.get("persona") or {}, adaptive_listing,
            selection.get("selected_patterns") or [], mode,
            selection.get("difficulty_adjustment") or "same",
            provider=settings.adaptive_provider_effective,
        )
        npc_varied = persona_variant.apply_variant_to_npc(npc, variant)
        new_json = json.dumps(npc_varied, ensure_ascii=False)
        ctx = {"counterparty_kind": counterparty_kind,
               "selection": selection, "variant": variant}
        return npc_varied, new_json, ctx
    except Exception:
        # 적응형이 어떤 이유로든 실패해도 기존 정적/동적 페르소나로 그대로 진행한다.
        return npc, session_npc_json, None


def _store_adaptive_context(conn, session_id, user_id, game_role, ctx) -> None:
    """선택된 패턴/변주를 서버 전용 컨텍스트 + 설명 이벤트로 남긴다 (best-effort)."""
    if not ctx:
        return
    try:
        sel = ctx.get("selection") or {}
        variant = ctx.get("variant") or {}
        adaptive_repository.insert_adaptive_context(
            conn, session_id, user_id,
            sel.get("selected_patterns"), sel.get("avoided_patterns"),
            sel.get("difficulty_adjustment"), variant,
        )
        adaptive_repository.insert_evolution_event(conn, {
            "user_id": user_id,
            "game_role": game_role,
            "new_session_id": session_id,
            "selected_persona_family": variant.get("scenario_type"),
            "selected_patterns_json": adaptive_repository.json_dumps(
                [p.get("pattern_key") for p in (sel.get("selected_patterns") or [])]),
            "avoided_patterns_json": adaptive_repository.json_dumps(
                [p.get("label") for p in (sel.get("avoided_patterns") or [])]),
            "difficulty_adjustment": sel.get("difficulty_adjustment"),
            "reason": sel.get("reason"),
            "provider": variant.get("provider", "template"),
        })
    except Exception:
        # 설명/컨텍스트 저장 실패는 게임에 영향 없음.
        pass


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

    # 적응형: 약점 위주 패턴 선택 + 안전한 페르소나 변주 (숨은 로직은 서버 전용; 실패 시 무영향)
    npc, session_npc_json, adaptive_ctx = _apply_adaptive_start(
        conn, user, npc, mode, session_npc_json, seller_listing
    )

    market_seed_json = (
        json.dumps(npc.get("listing"), ensure_ascii=False) if npc.get("listing") else None
    )

    session_id = str(uuid.uuid4())
    # 인바운드 문의에서 시작했다면, 거래 세션을 만들기 전에 그 문의를 '원자적으로 선점'한다.
    # 조건부 UPDATE 가 1행을 못 바꾸면(동시 수락·이미 응대·만료) 세션을 만들지 않고 409 로 거절한다.
    # 아직 아무것도 커밋하지 않았으므로 conn 종료 시 전부 롤백 → 같은 문의로 두 거래 세션이
    # 생겨 보상이 중복되는 것(리워드 파밍)을 막는다. (수락 카드는 화면/지도 양쪽에서 누를 수 있어
    # 더블클릭/동시요청이 실제로 발생할 수 있다.)
    if body.inquiry_id:
        from app import inquiries as inquiry_mgr
        if not inquiry_mgr.claim_inquiry(conn, user["id"], body.inquiry_id, session_id):
            raise HTTPException(
                status_code=409,
                detail="방금 다른 곳에서 응대를 시작했거나 만료된 문의예요. 다른 문의를 골라 주세요.",
            )
    # 아직 세션에 안 붙은 활성 미션(돌발 퀘스트)이 있으면 이번 세션에 연결한다.
    attached_mission = missions_mgr.attach_active_mission_to_session(conn, user["id"], session_id, mode)
    active_mission_id = attached_mission["id"] if attached_mission else None
    conn.execute(
        "INSERT INTO trade_sessions (id, user_id, npc_id, status, game_role, "
        "counterparty_kind, scenario_type, spawn_instance_id, session_npc_json, "
        "market_seed_json, active_mission_id, started_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, user["id"], npc["id"], mode, npc["npc_kind"],
         npc["role"], body.spawn_instance_id, session_npc_json, market_seed_json,
         active_mission_id, _now()),
    )
    # 선택된 패턴/변주를 서버 전용 컨텍스트로 저장 (프론트로는 안 나감)
    _store_adaptive_context(conn, session_id, user["id"], mode, adaptive_ctx)
    # Phase F: 승인된 시나리오 뱅크 seed 를 이번 훈련에 '참고'로 연결한다 (서버 전용·비권위적).
    #   NPC role/tactics/페르소나는 절대 바꾸지 않으므로 기존 생성 흐름이 그대로 유지된다.
    #   승인된 seed 가 없거나 실패하면 아무 일도 하지 않는다(기존 플로우 폴백).
    try:
        from app.scenarios import training_link
        mission_key = attached_mission.get("mission_key") if attached_mission else None
        training_link.link_seed_to_session(conn, user["id"], session_id, mode, mission_key)
    except Exception:
        pass
    # 말 건 스폰은 활성 풀에서 빼서 거래 도중 사라지지 않게 한다
    spawn_mgr.engage(conn, user["id"], body.spawn_instance_id)

    # ── 첫 메시지 정책 ──────────────────────────────────────────────
    # 구매자 모드(상대=판매자 NPC): 실제 중고앱처럼 '구매자(플레이어)가 먼저' 문의한다.
    #   → 판매자 NPC 오프닝을 자동 삽입하지 않는다. requires_player_first_message=true.
    # 판매자 모드(상대=구매자 NPC): 구매자가 내 판매글을 보고 '먼저 문의를 남긴' 상황이므로
    #   → 기존처럼 구매자 NPC 의 첫 문의(오프닝)를 보여준다.
    requires_player_first = (mode == "buyer")
    opening_payload = None
    if not requires_player_first:
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
        opening_payload = {"message_id": opening_row["id"], "content": opening["message"]}
    else:
        # NPC 오프닝 없이 세션만 만들고 커밋한다 (플레이어 첫 메시지 대기).
        conn.commit()

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
        # 구매자 모드면 판매자 NPC 가 먼저 말하지 않는다 → 플레이어가 첫 문의를 보내야 함.
        "requires_player_first_message": requires_player_first,
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
            # 얼굴 이미지: 스폰 id 만 담은 불투명 URL (family/role/gender 비노출).
            "portrait_url": _portrait_url(body.spawn_instance_id),
        },
        # 구매자 모드면 None — 프론트가 빈 채팅 + 빠른 문의 칩을 띄운다.
        "opening": opening_payload,
        "suggested_messages": _BUYER_SUGGESTED_MESSAGES if requires_player_first else [],
        "max_turns": _MAX_PLAYER_TURNS,
        # 이 세션에 연결된 활성 미션(돌발 퀘스트), 없으면 None.
        "mission": attached_mission,
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
    # 얼굴 이미지: 스폰 id 만 담은 불투명 URL (family/role/gender 비노출).
    # npc_id 폴백(디버그)일 땐 URL 을 만들 수 없어 None — npc_id 는 role 을 노출하므로 절대 URL 에 안 넣는다.
    card["portrait_url"] = _portrait_url(body.spawn_instance_id)

    # 판매자 모드: 구매자가 보낸 '첫 문의' 미리보기(중립·상품인지 — 유형 비노출).
    if mode == "seller":
        item = (seller_listing or {}).get("product_name") if seller_listing else None
        card["inquiry_preview"] = persona_factory.neutral_inquiry_preview(item, spawn_key)

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


def _maybe_generate_proof_photo(
    conn: sqlite3.Connection, user: sqlite3.Row, body: SendMessageRequest, npc: dict,
) -> str | None:
    """proof_first_buyer 미션 중 사진 요청이면, 조건이 맞을 때만 인증사진 한 장을 생성한다.

    - 세션에 연결된 활성 미션이 정확히 proof_first_buyer 여야 한다.
    - 이번 플레이어 메시지가 사진/인증 요청처럼 보여야 한다(missions.looks_like_proof_request).
    - 이 세션에서 아직 사진을 만든 적이 없어야 한다(세션당 최대 한 장 — 비용/스팸 방지).
    실제 생성은 image_gen.generate_proof_photo() 가 하며, 그 함수 자체가
    photo_generation_available=false(mock/local_claude)일 때 이미 None 을 돌려준다.
    """
    active_mission = missions_mgr.get_active_mission(conn, user["id"], session_id=body.session_id)
    if not active_mission or active_mission["mission_key"] != "proof_first_buyer":
        return None
    if not missions_mgr.looks_like_proof_request(body.message):
        return None
    already_has_photo = conn.execute(
        "SELECT 1 FROM chat_messages WHERE session_id = ? AND image_data_uri IS NOT NULL LIMIT 1",
        (body.session_id,),
    ).fetchone()
    if already_has_photo:
        return None
    return image_gen.generate_proof_photo(npc.get("item_name", ""), npc.get("item_category", ""))


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
    # 느린 NPC 응답(local_claude/openai 는 수 초~수십 초) 동안 쓰기 잠금을 붙들지 않도록
    # 플레이어 메시지를 '먼저' 커밋한다. 그래야 같은 시간에 들어오는 🚩 의심표시·스폰 폴링·
    # 다른 거래 쓰기가 'database is locked' 로 막히지 않는다. (WAL+busy_timeout 만으로는
    # 한 요청이 LLM 호출 내내 쓰기 트랜잭션을 점유하면 다른 쓰기가 타임아웃된다.)
    conn.commit()

    npc = _npc_from_session(conn, sess)
    seller_listing = (
        prefs_mgr.get_seller_listing(conn, user["id"]) if npc["npc_kind"] == "buyer" else None
    )
    agent = _make_agent(npc, user, seller_listing)
    updated_history = _load_history(conn, body.session_id)
    reply = agent.reply(updated_history)

    # proof_first_buyer 미션 중 실물/인증 사진을 요청하면, 사진 생성이 가능한 배포
    # 환경(openai 모드)에서만 세션당 한 장 인증사진을 만들어 이 NPC 답장에 붙인다.
    # 실패하거나 조건이 안 맞으면 그냥 None — 텍스트만으로 계속 진행된다(게임 흐름 유지).
    image_data_uri = _maybe_generate_proof_photo(conn, user, body, npc)

    conn.execute(
        "INSERT INTO chat_messages "
        "(session_id, turn_index, speaker, content, tactic, image_data_uri, created_at) "
        "VALUES (?, ?, 'npc', ?, ?, ?, ?)",
        (body.session_id, next_turn + 1, reply["message"], reply["tactic"],
         image_data_uri, _now()),
    )
    conn.commit()

    npc_row = conn.execute(
        "SELECT id FROM chat_messages WHERE session_id = ? AND turn_index = ?",
        (body.session_id, next_turn + 1),
    ).fetchone()

    return {
        "reply": {
            "message_id": npc_row["id"],
            "content": reply["message"],
            "image_data_uri": image_data_uri,
        },
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
def _record_adaptive(conn, user, sess, npc, transcript, result, decision, score,
                     correct, checked, rw) -> dict | None:
    """완료된 거래를 적응형 메모리에 기록하고, 결과 화면용 학습 요약을 돌려준다.

    설계: 규칙기반 채점(result)은 권위 그대로. 여기선 '훈련 신호'로만 환원한다.
    적응형이 꺼져 있거나(ADAPTIVE_SCENARIOS_ENABLED=false) 어떤 예외가 나도
    None 을 돌려주고, 기존 거래 흐름은 전혀 영향받지 않는다.
    """
    if not get_settings().adaptive_scenarios_enabled:
        return None
    try:
        enriched = dict(result)
        enriched["decision"] = decision
        enriched["score"] = score
        enriched["correct"] = correct
        return adaptive_memory.record_session_outcome(
            conn, user["id"], sess["id"],
            npc=npc, transcript=transcript, result=enriched,
            checklist=checked, rewards=rw,
            game_role=(sess["game_role"] if "game_role" in sess.keys() else None),
        )
    except Exception:
        # 적응형 기록이 어떤 이유로든 실패해도 게임/결과는 그대로 유지된다.
        return None


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
        "player_misconduct": -12,
    }.get(result["verdict"], 0)

    # 이 세션에 연결된 활성 미션(돌발 퀘스트)이 있으면 규칙 기반으로 채점하고 보너스를 반영한다.
    active_mission = missions_mgr.get_active_mission(conn, user["id"], session_id=sess["id"])
    mission_response = None
    if active_mission:
        mission_result = missions_mgr.evaluate_mission_completion(
            active_mission, result, transcript, checklist=checked
        )
        if mission_result["success"]:
            preview = active_mission.get("reward_preview") or {}
            xp_delta += preview.get("xp_bonus", 0)
            trust_delta += preview.get("trust_bonus", 0)
        mission_response = missions_mgr.finalize_mission(
            conn, user, active_mission["id"], mission_result
        )

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
    rw = _rewards(user, xp_delta, trust_delta, econ)
    _persist(conn, user, sess, npc, "buyer", result, score, correct,
             xp_delta, trust_delta, decision, econ, extras)
    learning = _record_adaptive(conn, user, sess, npc, transcript, result,
                                decision, score, correct, checked, rw)

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
        "rewards": rw,
        "reward_items": reward_items,
        "checklist": checked,
        "checklist_bonus": bonus,
        "aftermath": aftermath_mod.aftermath_for(result["verdict"]),
        "annotated_transcript": annotated,
        "learning": learning,
        "mission": mission_response,
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
        "missed_legitimate_claim": -6, "player_misconduct": -12,
    }.get(result["verdict"], 0)

    # 이 세션에 연결된 활성 미션(돌발 퀘스트)이 있으면 규칙 기반으로 채점하고 보너스를 반영한다.
    active_mission = missions_mgr.get_active_mission(conn, user["id"], session_id=sess["id"])
    mission_response = None
    if active_mission:
        mission_result = missions_mgr.evaluate_mission_completion(
            active_mission, result, transcript, checklist=checked
        )
        if mission_result["success"]:
            preview = active_mission.get("reward_preview") or {}
            xp_delta += preview.get("xp_bonus", 0)
            trust_delta += preview.get("trust_bonus", 0)
        mission_response = missions_mgr.finalize_mission(
            conn, user, active_mission["id"], mission_result
        )

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
    rw = _rewards(user, xp_delta, trust_delta, econ)
    _persist(conn, user, sess, npc, "seller", result, score, correct,
             xp_delta, trust_delta, decision, econ, extras)
    learning = _record_adaptive(conn, user, sess, npc, transcript, result,
                                decision, score, correct, checked, rw)

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
        "rewards": rw,
        "reward_items": reward_items,
        "checklist": checked,
        "checklist_bonus": bonus,
        "aftermath": aftermath_mod.aftermath_for(result["verdict"]),
        "annotated_transcript": annotated,
        "learning": learning,
        "mission": mission_response,
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
            "image_data_uri": m.get("image_data_uri"),
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
