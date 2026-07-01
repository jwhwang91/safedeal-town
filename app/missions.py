"""
미션 / 돌발 퀘스트 시스템.

직거래만 고집하면 항상 안전하다고 여기기 쉽지만, 실제로는 택배거래·플랫폼 안전결제·
증거 보존·경계 설정·침착한 분쟁 대응 같은 '현실적인 대안'도 연습이 필요하다.
이 모듈은 그런 훈련 시나리오(미션)를 제공·관리·채점한다.

중요:
  - 채점(evaluate_mission_completion)은 전부 규칙 기반이다. LLM 은 절대 성공/실패를 결정하지 않는다.
  - NPC 의 숨은 role/tactics(정답지)는 이 모듈이 다루지 않는다 — 미션은 '플레이어 행동'만 평가한다.
  - 미션은 시나리오 제약(자기 선언적 규칙)일 뿐, 실제 게임 메커니즘을 막지 않는다
    (직거래를 실제로 할 수 없게 만드는 게 아니라, '했을 때 미션이 실패로 채점되는' 방식).
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ============================================================
#  미션 카탈로그 (정적 정의 — DB 아님)
# ============================================================
MISSION_CATALOG: list[dict] = [
    # ---------------- 구매자 모드 ----------------
    {
        "mission_key": "delivery_only_buyer",
        "game_role": "buyer",
        "title": "택배거래로 안전하게 구매하기",
        "situation": "당신은 현재 해외/출장/육아 등으로 직거래가 어렵습니다. "
                     "이번 거래는 택배거래로만 진행해야 합니다.",
        "constraints": {
            "direct_trade_allowed": False,
            "delivery_required": True,
            "platform_chat_required": True,
            "external_link_forbidden": True,
        },
        "success_hint": "실물 인증을 요청하고, 상태/구성품을 확인하고, 외부 링크는 거절하며, "
                         "안전한 절차로만 진행하세요.",
        "reward_preview": {"xp_bonus": 18, "trust_bonus": 5,
                            "badge_name": "배송거래 생존자 배지", "item_bonus": True},
        "badge_item_id": "badge_delivery_survivor",
    },
    {
        "mission_key": "safe_payment_buyer",
        "game_role": "buyer",
        "title": "안전결제로 거래 완료하기",
        "situation": "이번 거래는 플랫폼 안전결제만 사용하세요. "
                     "외부 결제 페이지나 개인 결제 링크는 받지 않습니다.",
        "constraints": {
            "safe_payment_required": True,
            "external_payment_forbidden": True,
            "private_payment_link_forbidden": True,
        },
        "success_hint": "안전결제 절차를 확인하고, 외부 결제 페이지·개인 링크 요구는 거절하세요.",
        "reward_preview": {"xp_bonus": 15, "trust_bonus": 4,
                            "badge_name": "플랫폼 안전결제 숙련자 배지", "item_bonus": True},
        "badge_item_id": "badge_safe_payment_pro",
    },
    {
        "mission_key": "proof_first_buyer",
        "game_role": "buyer",
        "title": "실물 인증 받고 구매하기",
        "situation": "실물 사진, 오늘 날짜가 보이는 인증 사진, 구성품/상태를 확인한 뒤에만 "
                     "구매를 결정하세요.",
        "constraints": {"proof_required": True},
        "success_hint": "실물 사진과 날짜 인증, 구성품/상태 확인을 요청한 뒤 결정하세요.",
        "reward_preview": {"xp_bonus": 15, "trust_bonus": 4,
                            "badge_name": "증거 중심 대응 배지", "item_bonus": True},
        "badge_item_id": "badge_evidence_first",
        # 이 미션은 상대가 실제로 '인증 사진'을 만들어 보여줄 수 있어야 의미가 있다.
        # 사진을 생성할 방법이 없는 배포 환경(mock/local_claude)에서는 제안하지 않는다.
        "requires_photo_generation": True,
    },
    {
        "mission_key": "boundary_keeper_buyer",
        "game_role": "buyer",
        "title": "사적 연락 유도 거절하기",
        "situation": "상대가 전화번호·메신저 교환이나 사적인 만남을 유도합니다. "
                     "플랫폼 안에서만 대응하세요.",
        "constraints": {"platform_chat_required": True, "private_contact_forbidden": True},
        "success_hint": "플랫폼 밖 연락처 교환에는 응하지 말고, 대화를 상품/거래 이야기로 유지하세요.",
        "reward_preview": {"xp_bonus": 15, "trust_bonus": 5,
                            "badge_name": "경계 지킴이 배지", "item_bonus": True},
        "badge_item_id": "badge_boundary_keeper",
    },
    # ---------------- 판매자 모드 ----------------
    {
        "mission_key": "delivery_safe_seller",
        "game_role": "seller",
        "title": "택배거래로 안전하게 판매하기",
        "situation": "구매자가 택배거래를 원합니다. 판매 전 상태 기록과 플랫폼 내 대화를 유지하며 "
                     "안전하게 판매하세요.",
        "constraints": {"delivery_required": True, "platform_chat_required": True},
        "success_hint": "상품 상태를 명확히 고지하고, 증거(사진/대화)를 남기고, "
                         "대화는 플랫폼 안에서 유지하세요.",
        "reward_preview": {"xp_bonus": 18, "trust_bonus": 5,
                            "badge_name": "배송거래 생존자 배지", "item_bonus": True},
        "badge_item_id": "badge_delivery_survivor",
    },
    {
        "mission_key": "refund_boundary_seller",
        "game_role": "seller",
        "title": "부당 환불 요구 대응하기",
        "situation": "환불 요구가 들어왔습니다. 감정적으로 대응하지 말고 기록 중심으로 대응하세요.",
        "constraints": {"evidence_based_response_required": True},
        "success_hint": "고지·기록을 근거로 침착하게 대응하고, 필요하면 플랫폼 분쟁 절차를 안내하세요.",
        "reward_preview": {"xp_bonus": 15, "trust_bonus": 5,
                            "badge_name": "증거 중심 대응 배지", "item_bonus": True},
        "badge_item_id": "badge_evidence_first",
    },
    {
        "mission_key": "private_contact_refusal_seller",
        "game_role": "seller",
        "title": "사적 연락 요구 거절하기",
        "situation": "구매자가 사적 연락을 요구합니다. 플랫폼 안에서만 대응하세요.",
        "constraints": {"platform_chat_required": True, "private_contact_forbidden": True},
        "success_hint": "연락처 교환 요구는 거절하고, 거래 이야기로만 대화를 이어가세요.",
        "reward_preview": {"xp_bonus": 15, "trust_bonus": 5,
                            "badge_name": "경계 지킴이 배지", "item_bonus": True},
        "badge_item_id": "badge_boundary_keeper",
    },
    {
        "mission_key": "lowball_boundary_seller",
        "game_role": "seller",
        "title": "과도한 네고에 기준선 지키기",
        "situation": "구매자가 과도한 가격 네고를 반복해서 요구합니다. 침착하게 기준선을 지키세요.",
        "constraints": {"price_boundary_required": True},
        "success_hint": "감정적으로 대응하지 말고 최종 가격/기준을 명확히 밝히고, "
                         "계속되면 거래를 정리하세요.",
        "reward_preview": {"xp_bonus": 12, "trust_bonus": 4,
                            "badge_name": "비매너 차단 배지", "item_bonus": True},
        "badge_item_id": "badge_manner_blocker",
    },
]

_CATALOG_BY_KEY = {m["mission_key"]: m for m in MISSION_CATALOG}


def mission_game_role(mission_key: str) -> str | None:
    """이 미션 키가 어느 모드(buyer/seller) 소속인지. 알 수 없는 키면 None."""
    entry = _CATALOG_BY_KEY.get(mission_key)
    return entry["game_role"] if entry else None


def _public_catalog_entry(m: dict) -> dict:
    """카탈로그 정의에서 공개해도 되는 필드만 골라낸다 (badge_item_id 등 내부 필드 제외)."""
    return {
        "mission_key": m.get("mission_key"),
        "game_role": m.get("game_role"),
        "title": m.get("title"),
        "situation": m.get("situation", ""),
        "constraints": dict(m.get("constraints") or {}),
        "success_hint": m.get("success_hint", ""),
        "reward_preview": dict(m.get("reward_preview") or {}),
    }


def _public_item(it: dict) -> dict:
    return {
        "id": it["id"], "name": it["name"], "item_type": it["item_type"],
        "rarity": it["rarity"], "description": it.get("description", ""),
    }


def _public_active_mission(row: sqlite3.Row) -> dict:
    """DB row(mission_json 포함) → 공개 응답 dict."""
    mission = None
    try:
        mission = json.loads(row["mission_json"]) if row["mission_json"] else None
    except (json.JSONDecodeError, TypeError):
        mission = None
    if not mission:
        mission = _CATALOG_BY_KEY.get(row["mission_key"]) or {
            "mission_key": row["mission_key"], "game_role": row["game_role"],
            "title": row["mission_key"], "situation": "", "constraints": {},
            "success_hint": "", "reward_preview": {},
        }
    payload = _public_catalog_entry(mission)
    payload.update({
        "id": row["id"],
        "status": row["status"],
        "session_id": row["session_id"],
        "created_at": row["created_at"],
    })
    return payload


# ============================================================
#  조회 / 제안 / 수락 / 포기
# ============================================================
def mission_requires_photo(mission_key: str) -> bool:
    """이 미션이 (아직 어디서도 실제로 만들지 않는) 인증 사진 생성을 전제로 하는지."""
    entry = _CATALOG_BY_KEY.get(mission_key)
    return bool(entry and entry.get("requires_photo_generation"))


def _catalog_pool(game_role: str, context: dict | None = None) -> list[dict]:
    """이 모드에서 지금 고를 수 있는 미션(내부용 카탈로그 dict) 목록.

    context.photo_generation_available 가 falsy 면(mock/local_claude 등 사진을 만들 방법이
    없는 배포 환경) requires_photo_generation 미션은 애초에 후보에서 뺀다 —
    플레이어가 완료할 수 없는 미션을 제안하지 않기 위함.
    """
    role = game_role if game_role in ("buyer", "seller") else "buyer"
    photo_ok = bool((context or {}).get("photo_generation_available"))
    pool = [m for m in MISSION_CATALOG if m["game_role"] == role]
    if not photo_ok:
        pool = [m for m in pool if not m.get("requires_photo_generation")]
    return pool


def get_available_missions(game_role: str, context: dict | None = None) -> list[dict]:
    """이 모드(buyer/seller)에서 고를 수 있는 미션 카탈로그(정적 정의).

    context 로 {"photo_generation_available": bool} 을 넘기면, 사진 생성이 필요한
    미션은 그 값이 true 일 때만 목록에 포함된다.
    """
    return [_public_catalog_entry(m) for m in _catalog_pool(game_role, context)]


def _last_mission_key(conn: sqlite3.Connection, user_id: int, game_role: str) -> str | None:
    row = conn.execute(
        "SELECT mission_key FROM user_active_missions WHERE user_id = ? AND game_role = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id, game_role),
    ).fetchone()
    return row["mission_key"] if row else None


def offer_mission(conn: sqlite3.Connection, user_id: int, game_role: str,
                  context: dict | None = None) -> dict | None:
    """지금 제안할 미션 하나를 고른다.

    이미 활성 미션이 있으면 새로 제안하지 않는다(None). 직전 미션과 같은 키는
    가능하면 피해서(반복 방지) 다양성을 준다. 아직 수락된 건 아니므로 DB 에 아무것도 쓰지 않는다
    — 실제 활성화는 accept_mission() 이 한다. 후보 풀은 _catalog_pool() 과 동일한 규칙으로
    사진 생성 필요 미션을 걸러낸다(get_available_missions() 와 일관되게).
    """
    role = game_role if game_role in ("buyer", "seller") else "buyer"
    if get_active_mission(conn, user_id, game_role=role):
        return None
    pool = _catalog_pool(role, context)
    if not pool:
        return None
    last_key = _last_mission_key(conn, user_id, role)
    candidates = [m for m in pool if m["mission_key"] != last_key] or pool
    rng = random.Random()
    return _public_catalog_entry(rng.choice(candidates))


def accept_mission(conn: sqlite3.Connection, user_id: int, mission_key: str,
                   session_id: str | None = None) -> dict:
    """미션을 수락해 활성화한다.

    같은 모드(game_role)의 기존 활성 미션이 있으면 건너뛴 것으로 처리한다
    (사용자당 모드별로 활성 미션은 항상 최대 1개).
    """
    mission = _CATALOG_BY_KEY.get(mission_key)
    if not mission:
        raise ValueError(f"알 수 없는 미션입니다: {mission_key}")
    game_role = mission["game_role"]
    conn.execute(
        "UPDATE user_active_missions SET status = 'skipped' "
        "WHERE user_id = ? AND game_role = ? AND status = 'active'",
        (user_id, game_role),
    )
    mission_id = _new_id()
    conn.execute(
        "INSERT INTO user_active_missions "
        "(id, user_id, session_id, mission_key, game_role, mission_json, status, reward_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', '{}', ?)",
        (mission_id, user_id, session_id, mission_key, game_role,
         json.dumps(mission, ensure_ascii=False), _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM user_active_missions WHERE id = ?", (mission_id,)
    ).fetchone()
    return _public_active_mission(row)


def skip_mission(conn: sqlite3.Connection, user_id: int, mission_id: str) -> None:
    """활성 미션을 포기(건너뛰기)한다. 본인 소유 + 아직 active 인 경우만."""
    conn.execute(
        "UPDATE user_active_missions SET status = 'skipped' "
        "WHERE id = ? AND user_id = ? AND status = 'active'",
        (mission_id, user_id),
    )
    conn.commit()


def get_active_mission(conn: sqlite3.Connection, user_id: int,
                       session_id: str | None = None,
                       game_role: str | None = None) -> dict | None:
    """활성 미션 조회.

    session_id 를 주면 그 세션에 연결된 활성 미션만(거래 판정용).
    없으면 game_role 기준 가장 최근 활성 미션(HUD/제안용). 둘 다 없으면 사용자의 아무 활성 미션.
    """
    if session_id:
        row = conn.execute(
            "SELECT * FROM user_active_missions WHERE user_id = ? AND session_id = ? AND status = 'active'",
            (user_id, session_id),
        ).fetchone()
    elif game_role:
        row = conn.execute(
            "SELECT * FROM user_active_missions WHERE user_id = ? AND game_role = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, game_role),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM user_active_missions WHERE user_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return _public_active_mission(row) if row else None


def attach_active_mission_to_session(conn: sqlite3.Connection, user_id: int,
                                     session_id: str, game_role: str) -> dict | None:
    """세션 시작 시, 아직 세션에 안 붙은 활성 미션이 있으면 이번 세션에 연결한다.

    커밋은 호출자(start_chat)가 트랜잭션 마지막에 한 번에 한다.
    """
    row = conn.execute(
        "SELECT * FROM user_active_missions WHERE user_id = ? AND game_role = ? "
        "AND status = 'active' AND session_id IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id, game_role),
    ).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE user_active_missions SET session_id = ? WHERE id = ?",
        (session_id, row["id"]),
    )
    mission = _public_active_mission(row)
    mission["session_id"] = session_id
    return mission


# ============================================================
#  채점 (규칙 기반 — LLM 관여 없음)
# ============================================================
_DIRECT_ONLY_KEYWORDS = ("직거래", "직접 만나", "얼굴 보고 거래")
_SAFE_METHOD_KEYWORDS = ("택배", "안전결제", "안심결제", "비대면", "안전 결제", "네이버페이",
                         "당근페이", "안전 배송")
_PROOF_KEYWORDS = ("사진", "인증", "영상통화", "실물", "메모")
_PRIVATE_CONTACT_RE = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
_PRIVATE_CONTACT_KEYWORDS = ("카톡", "카카오톡", "인스타", "전화번호", "번호 알려", "번호로",
                             "따로 연락", "개인 연락", "디엠")

_GOOD_SELLER_VERDICTS = {"fair_sale", "handled_refund_villain", "handled_lowballer",
                         "handled_risky", "ok_walkaway"}


def _player_texts(transcript: list[dict]) -> list[str]:
    return [str(m.get("content") or "") for m in (transcript or []) if m.get("speaker") == "player"]


def _has_keyword(texts: list[str], keywords: tuple[str, ...]) -> bool:
    return any(kw in t for t in texts for kw in keywords)


def looks_like_proof_request(text: str) -> bool:
    """이 플레이어 메시지가 '실물/인증 사진'을 요청하는 것처럼 보이는지.

    evaluate_mission_completion 의 proof_first_buyer 판정과 같은 키워드 기준을 쓴다 —
    채점에서 '요청했다'고 인정하는 시점과 인증사진 생성을 트리거하는 시점이 어긋나지
    않도록 하기 위함이다.
    """
    return _has_keyword([text or ""], _PROOF_KEYWORDS)


def _flags_mention(flags, markers: tuple[str, ...]) -> bool:
    return any(any(mk in (f or "") for mk in markers) for f in (flags or []))


def _leaked_private_contact(texts: list[str]) -> bool:
    if any(_PRIVATE_CONTACT_RE.search(t) for t in texts):
        return True
    return _has_keyword(texts, _PRIVATE_CONTACT_KEYWORDS)


def _eval_delivery_only_buyer(verdict, correct, missed, texts, checked):
    if verdict == "scammed" or _flags_mention(missed, ("링크", "외부", "선입금")):
        return False, "외부 링크·선입금 같은 위험 신호를 놓쳐 안전하게 거래를 마치지 못했어요.", \
            "택배거래에서도 실물 인증·플랫폼 절차 없이 외부 링크·선입금 요구에 응하면 위험해요."
    direct_only = (
        _has_keyword(texts, _DIRECT_ONLY_KEYWORDS)
        and "safe_method" not in checked
        and not _has_keyword(texts, _SAFE_METHOD_KEYWORDS)
    )
    if direct_only:
        return False, "직거래만 고집해서 택배거래 훈련 목표를 달성하지 못했어요.", \
            "이번 미션은 직거래가 불가능한 상황에서 택배거래를 안전하게 판단하는 훈련이었어요."
    safe_ok = "safe_method" in checked or _has_keyword(texts, _SAFE_METHOD_KEYWORDS)
    proof_ok = ("proof_request" in checked or "condition_check" in checked
                or _has_keyword(texts, _PROOF_KEYWORDS))
    if safe_ok and proof_ok and correct:
        return True, "실물 인증을 챙기며 택배거래를 안전하게 완료했어요.", \
            "직거래가 어려운 상황에서도 인증·안전한 절차를 지키면 안전하게 거래할 수 있어요."
    return False, "택배거래에 필요한 인증·안전 절차 확인이 충분하지 않았어요.", \
        "택배거래에서는 실물/구성품 인증과 안전한 절차 확인이 특히 중요해요."


def _eval_safe_payment_buyer(verdict, correct, missed, texts, checked):
    if verdict == "scammed" or _flags_mention(missed, ("링크", "외부", "선입금", "계좌")):
        return False, "안전결제 대신 위험한 결제 신호에 노출됐어요.", \
            "외부 결제 페이지나 개인 링크는 아무리 급해도 거절하는 게 안전해요."
    safe_ok = "safe_method" in checked or _has_keyword(texts, ("안전결제", "안심결제", "안전 결제"))
    if safe_ok and correct:
        return True, "외부 결제 없이 플랫폼 안전결제 절차를 지켰어요.", \
            "결제는 플랫폼 안전결제로만 진행하면 대부분의 결제 사기를 피할 수 있어요."
    return False, "플랫폼 안전결제를 명확히 챙기지 못했어요.", \
        "결제 전엔 항상 '플랫폼 안전결제인가?'를 스스로 확인하는 습관이 중요해요."


def _eval_proof_first_buyer(verdict, correct, missed, texts, checked):
    proof_ok = "proof_request" in checked or _has_keyword(texts, _PROOF_KEYWORDS)
    if not proof_ok:
        return False, "구매 전 실물 인증을 요청하지 않았어요.", \
            "실물 사진·날짜 인증·구성품 확인 없이 구매를 결정하면 하자/사기를 놓치기 쉬워요."
    if verdict == "scammed":
        return False, "인증을 요청했지만 다른 위험 신호를 놓쳤어요.", \
            "인증 요청과 함께 다른 위험 신호(선입금, 외부 링크 등)도 같이 살펴야 해요."
    if correct:
        return True, "실물 인증과 상태/구성품 확인을 거친 뒤 판단했어요.", \
            "구매 전 실물·날짜 인증을 요청하는 습관은 하자 상품과 사기를 함께 걸러줘요."
    return False, "인증은 요청했지만 최종 판단이 정확하지 않았어요.", \
        "인증 요청도 중요하지만, 받은 인증 내용을 실제로 판단에 반영해야 해요."


def _eval_boundary_keeper_buyer(verdict, correct, missed, texts, checked):
    if verdict == "player_misconduct":
        return False, "부적절한 대응으로 경계를 지키지 못했어요.", \
            "불편한 요구는 정중하지만 단호하게, 플랫폼 안에서 거절하는 게 안전해요."
    if _leaked_private_contact(texts):
        return False, "사적 연락처를 주고받아 플랫폼 밖으로 대화가 넘어갔어요.", \
            "전화번호·메신저 교환 요구는 아무리 자연스러워 보여도 플랫폼 안에서 거절하는 게 안전해요."
    return True, "사적 연락 요구를 플랫폼 안에서 잘 거절했어요.", \
        "사적 연락 유도는 흔한 접근 방식이에요. 플랫폼 안에서만 대응하면 대부분의 위험을 피할 수 있어요."


def _eval_delivery_safe_seller(verdict, correct, missed, texts, checked):
    if verdict in ("over_refunded", "unsafe_response", "player_misconduct"):
        return False, "판매 과정에서 위험하거나 손해가 큰 대응을 했어요.", \
            "택배거래에서도 상태 고지·증거·플랫폼 대화 유지가 분쟁을 막는 핵심이에요."
    disclosed = "disclose_condition" in checked or _has_keyword(texts, ("상태", "고지"))
    if disclosed and correct:
        return True, "상태를 고지하고 플랫폼 안에서 안전하게 택배거래를 마쳤어요.", \
            "택배거래는 상태 고지와 증거 기록만 잘 해두면 직거래 못지않게 안전할 수 있어요."
    return False, "상품 상태 고지나 증거 기록이 충분하지 않았어요.", \
        "택배거래 전엔 상태를 명확히 고지하고 사진 등 증거를 남겨두는 게 중요해요."


def _eval_refund_boundary_seller(verdict, correct, missed, texts, checked):
    if verdict in ("unsafe_response", "player_misconduct"):
        return False, "감정적이거나 위험한 방식으로 대응했어요.", \
            "환불 요구엔 감정 대신 고지 내용과 기록을 근거로 침착하게 대응하는 게 안전해요."
    if verdict == "over_refunded":
        return False, "근거 없이 과도하게 환불해줬어요.", \
            "환불은 근거(고지 내용/상태 기록)를 기준으로 판단해야 해요. 무조건적인 환불은 오히려 나쁜 선례가 돼요."
    if verdict in _GOOD_SELLER_VERDICTS or correct:
        return True, "기록과 근거를 바탕으로 침착하게 환불 요구에 대응했어요.", \
            "부당한 환불 요구엔 감정적으로 반응하지 말고, 고지 내용과 기록으로 침착하게 대응하세요."
    return False, "정당한 요구를 놓쳤거나 판단이 정확하지 않았어요.", \
        "환불 대응은 감정이 아니라 사실과 기록을 기준으로 판단해야 해요."


def _eval_private_contact_refusal_seller(verdict, correct, missed, texts, checked):
    if verdict == "player_misconduct":
        return False, "부적절한 대응으로 상황을 악화시켰어요.", \
            "불편한 요구는 정중하지만 단호하게 플랫폼 안에서 거절하는 게 안전해요."
    if _leaked_private_contact(texts):
        return False, "사적 연락처를 주고받아 플랫폼 밖으로 대화가 넘어갔어요.", \
            "구매자가 사적 연락을 요구해도 플랫폼 안에서만 대응하는 게 안전해요."
    return True, "사적 연락 요구를 플랫폼 안에서 잘 거절했어요.", \
        "사적 연락 요구는 플랫폼 밖 분쟁·괴롭힘으로 이어지기 쉬워요. 항상 플랫폼 안에서 대응하세요."


def _eval_lowball_boundary_seller(verdict, correct, missed, texts, checked):
    if verdict in ("unsafe_response", "player_misconduct"):
        return False, "감정적이거나 무례한 방식으로 대응했어요.", \
            "과도한 네고에도 침착하게 기준선을 밝히는 게 서로에게 안전해요."
    if verdict in _GOOD_SELLER_VERDICTS or correct:
        return True, "과도한 네고에도 침착하게 기준선을 지켰어요.", \
            "가격 기준을 명확히 밝히고, 계속되는 압박엔 거래를 정리하는 것도 괜찮은 선택이에요."
    return False, "기준선을 지키지 못하고 과도하게 밀렸어요.", \
        "네고 압박에 계속 밀리기보다, 기준을 정중하게 밝히는 연습이 필요해요."


_EVALUATORS = {
    "delivery_only_buyer": _eval_delivery_only_buyer,
    "safe_payment_buyer": _eval_safe_payment_buyer,
    "proof_first_buyer": _eval_proof_first_buyer,
    "boundary_keeper_buyer": _eval_boundary_keeper_buyer,
    "delivery_safe_seller": _eval_delivery_safe_seller,
    "refund_boundary_seller": _eval_refund_boundary_seller,
    "private_contact_refusal_seller": _eval_private_contact_refusal_seller,
    "lowball_boundary_seller": _eval_lowball_boundary_seller,
}


def evaluate_mission_completion(mission: dict, result: dict, transcript: list[dict],
                                checklist: list[str] | None = None) -> dict:
    """미션 성공/실패를 규칙 기반으로 판정한다 (LLM 은 절대 관여하지 않는다).

    mission: get_active_mission() 등이 돌려준 공개 미션 dict (mission_key 포함).
    result: JudgeAgent.evaluate[_seller_mode]() 의 채점 결과 dict.
    transcript: 이 세션의 대화 기록 (chat_messages 형태의 dict 리스트).
    checklist: 플레이어가 자기보고한 체크리스트 키 목록(선택).
    """
    key = mission.get("mission_key")
    title = mission.get("title", key)
    checked = set(checklist or [])
    texts = _player_texts(transcript)
    verdict = result.get("verdict")
    correct = bool(result.get("correct"))
    missed = result.get("missed_flags") or []

    evaluator = _EVALUATORS.get(key)
    if evaluator:
        success, reason, lesson = evaluator(verdict, correct, missed, texts, checked)
    else:
        success, reason, lesson = True, "이 미션은 별도 평가 규칙이 없어 완료로 처리했어요.", ""

    return {
        "mission_key": key,
        "title": title,
        "success": bool(success),
        "reason": reason,
        "lesson": lesson,
    }


# ============================================================
#  완료 처리 (보상 지급 + 저장)
# ============================================================
def finalize_mission(conn: sqlite3.Connection, user: sqlite3.Row, mission_row_id: str,
                     mission_result: dict) -> dict:
    """미션 결과를 저장하고, 성공 시 배지/보너스 아이템을 지급한다.

    반환: 결과 모달에 그대로 넘길 수 있는 공개 dict.
    커밋은 호출자(resolve_trade 쪽의 _persist)가 트랜잭션 마지막에 한 번에 한다.
    """
    from app import rewards as rewards_mgr  # 지연 import: 순환 임포트 방지

    catalog_entry = _CATALOG_BY_KEY.get(mission_result["mission_key"], {})
    reward_preview = catalog_entry.get("reward_preview", {})
    success = mission_result["success"]

    xp_bonus = reward_preview.get("xp_bonus", 0) if success else 0
    trust_bonus = reward_preview.get("trust_bonus", 0) if success else 0
    badge_gained = None
    bonus_items: list[dict] = []

    if success:
        badge_id = catalog_entry.get("badge_item_id")
        if badge_id and rewards_mgr.grant_item(conn, user["id"], badge_id):
            it = rewards_mgr.ITEMS_BY_ID.get(badge_id)
            if it:
                badge_gained = _public_item(it)
        if reward_preview.get("item_bonus"):
            rng = random.Random()
            ids = rewards_mgr.roll_item_rewards(95, "medium", "", "good_catch", True, rng)
            for item_id in ids:
                if rewards_mgr.grant_item(conn, user["id"], item_id):
                    it = rewards_mgr.ITEMS_BY_ID.get(item_id)
                    if it:
                        bonus_items.append(_public_item(it))

    reward_payload = {
        "xp_bonus": xp_bonus, "trust_bonus": trust_bonus,
        "badge_gained": badge_gained, "bonus_items": bonus_items,
        "reason": mission_result["reason"], "lesson": mission_result["lesson"],
    }
    conn.execute(
        "UPDATE user_active_missions SET status = ?, reward_json = ?, completed_at = ? WHERE id = ?",
        ("completed" if success else "failed",
         json.dumps(reward_payload, ensure_ascii=False), _now(), mission_row_id),
    )
    return {
        "mission_key": mission_result["mission_key"],
        "title": mission_result["title"],
        "success": success,
        "reason": mission_result["reason"],
        "lesson": mission_result["lesson"],
        "xp_bonus": xp_bonus,
        "trust_bonus": trust_bonus,
        "badge_gained": badge_gained,
        "bonus_items": bonus_items,
    }
