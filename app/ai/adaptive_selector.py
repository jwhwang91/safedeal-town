"""
적응형 시나리오 선택기.

사용자의 누적 훈련 메모리를 보고, 미래 세션이 '약한 위험 신호'를 더 자주 훈련하고
'이미 숙달했고 최근 반복된' 신호는 잠시 피하도록 패턴 가족과 난이도를 고른다.

⚠️ 안전: 이 선택은 '정답'을 바꾸지 않는다. 규칙기반 JudgeAgent 가 여전히 권위.
선택 결과(숨은 적응 로직)는 결과 화면 전에는 절대 프론트로 내려가지 않는다.
숨은 컨텍스트는 ai_session_adaptive_context(서버 전용)에만 저장된다.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

from app.ai import adaptive_repository as repo
from app.ai import pattern_taxonomy as taxonomy
from app.config import get_settings

# 상대 종류 → 그 상대가 보일 수 있는 '훈련 후보' 패턴 키 (앵커 NPC 플레이북과 정렬)
_CANDIDATES_BY_COUNTERPARTY: dict[str, list[str]] = {
    # 구매자 모드 (판매자 NPC)
    "scam_seller": [p["pattern_key"] for p in taxonomy.BUYER_PATTERNS],
    "honest_seller": [],
    "rude_but_honest_seller": [],
    "professional_seller": [],
    # 판매자 모드 (구매자 NPC)
    "refund_villain": [
        "seller_ignore_disclosure", "seller_unreasonable_refund",
        "seller_review_threat", "seller_report_threat", "seller_self_inflicted_damage",
    ],
    "lowballer": ["seller_excessive_lowball", "seller_guilt_trip"],
    "ghosting_buyer": ["seller_ghosting"],
    "risky_buyer": ["seller_off_platform_pay", "seller_risky_pickup"],
    "legitimate_claim_buyer": ["seller_legit_defect_claim"],
    "honest_buyer": [],
}


def _is_avoided(mem_row: dict | None, now: datetime) -> bool:
    """이미 숙달 + 최근이라 잠시 덜 등장시켜야 하는 패턴인가."""
    if not mem_row:
        return False
    until = mem_row.get("avoid_repetition_until")
    if not until:
        return False
    try:
        dt = datetime.fromisoformat(until)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > now


def _difficulty_adjustment(avg_mastery: float, history_count: int) -> str:
    """전반 숙련도로 난이도 가감을 정한다."""
    if history_count <= 0:
        return "same"
    if avg_mastery >= 0.75:
        return "harder"   # 잘하면 더 미묘하게
    if avg_mastery < 0.4:
        return "easier"   # 어려워하면 더 분명하게
    return "same"


def _clamp_difficulty_adjustment(adjustment: str, npc_difficulty: str | None) -> str:
    """현재 상대 NPC 의 실제 난이도를 벗어나는 가감은 'same' 으로 눌러준다.

    (이미 hard 인 상대를 더 어렵게, 또는 이미 easy 인 상대를 더 쉽게 요구하지 않도록 —
    select_adaptive_patterns 의 difficulty 인자를 실제로 반영하는 지점.)
    """
    d = (npc_difficulty or "medium").lower()
    if adjustment == "harder" and d == "hard":
        return "same"
    if adjustment == "easier" and d == "easy":
        return "same"
    return adjustment


def _pattern_brief(pattern_key: str) -> dict | None:
    """선택된 패턴의 서버 전용 요약(persona_variant 가 쓰는 안전 재료)."""
    p = taxonomy.get_pattern(pattern_key)
    if not p:
        return None
    return {
        "pattern_key": p["pattern_key"],
        "pattern_family": p["pattern_family"],
        "label": p["label"],
        "red_flag": p["red_flag"],
        "safe_counter": p["safe_counter"],
        "severity": p["severity"],
        "allowed_simulation_style": p["allowed_simulation_style"],
    }


# ============================================================
#  사용자 훈련 프로필 (리포트/선택 공용)
# ============================================================
def get_user_training_profile(conn: sqlite3.Connection, user_id: int,
                              game_role: str) -> dict:
    """패턴별 숙련도 + 약점/강점/추천 난이도 + UI 요약을 만든다."""
    role = "seller" if game_role == "seller" else "buyer"
    memory = {m["pattern_key"]: m for m in repo.get_training_memory(conn, user_id, role)}
    history_count = repo.count_completed_outcomes(conn, user_id, role)

    mastery_by_pattern: dict[str, dict] = {}
    weak, mastered, recent, untrained = [], [], [], []
    mastery_values = []

    for pat in taxonomy.patterns_for_role(role):
        pk = pat["pattern_key"]
        mem = memory.get(pk)
        seen = int(mem["times_seen"]) if mem else 0
        mastery = float(mem["mastery_score"]) if mem else 0.0
        card = {
            "pattern_key": pk,
            "label": pat["label"],
            "pattern_family": pat["pattern_family"],
            "times_seen": seen,
            "mastery": round(mastery, 3),
            "mastery_pct": round(mastery * 100),
        }
        mastery_by_pattern[pk] = card
        if seen == 0:
            untrained.append(pk)
            continue
        mastery_values.append(mastery)
        if mastery < 0.4:
            weak.append(pk)
        elif mastery > 0.8:
            mastered.append(pk)
        if mem and mem.get("last_seen_at"):
            recent.append(pk)

    avg_mastery = round(sum(mastery_values) / len(mastery_values), 3) if mastery_values else 0.0
    difficulty = _difficulty_adjustment(avg_mastery, history_count)

    return {
        "game_role": role,
        "history_count": history_count,
        "avg_mastery": avg_mastery,
        "mastery_by_pattern": mastery_by_pattern,
        "weak_patterns": weak,
        "mastered_patterns": mastered,
        "recent_patterns": recent,
        "untrained_patterns": untrained,
        "recommended_difficulty": difficulty,
    }


# ============================================================
#  패턴 선택
# ============================================================
def select_adaptive_patterns(conn: sqlite3.Connection, user_id: int, game_role: str,
                             counterparty_kind: str, category: str | None = None,
                             difficulty: str | None = None, limit: int = 2) -> dict:
    """미래 세션에서 강조할 패턴 가족 + 난이도 가감을 고른다.

    규칙:
      1. 완료 세션이 ADAPTIVE_MIN_HISTORY_FOR_PERSONALIZATION 미만 → 균형 기본 선택.
      2. 숙련도>0.8 + 최근 → 잠시 피한다.
      3. 숙련도<0.4 → 우선한다.
      4. 약점이 분명하면 더 분명한 신호, 잘하면 더 미묘하게 (난이도 가감).
      7. 결정적이지 않도록 약간의 무작위성을 섞는다.
    """
    role = "seller" if game_role == "seller" else "buyer"
    settings = get_settings()
    candidates = list(_CANDIDATES_BY_COUNTERPARTY.get(counterparty_kind, []))
    profile = get_user_training_profile(conn, user_id, role)
    # difficulty: 현재 NPC 의 실제 난이도 → 가감 클램프에 사용(아래).
    # category: 사용자가 고른 구매 카테고리(구매자 모드) / 판매글 카테고리(판매자 모드).
    #   후보(candidates)는 이미 '상대 종류'로 한정돼 있어 무관한 품목 카테고리로 새지 않는다.
    #   여기선 category 를 '서버 전용 컨텍스트'로 기록해, 변주가 이 카테고리/판매글 안에서만
    #   다양해지도록 한다 (정답 라벨은 바꾸지 않는다).
    recommended_adj = _clamp_difficulty_adjustment(profile["recommended_difficulty"], difficulty)

    base = {
        "selected_patterns": [],
        "avoided_patterns": [],
        "difficulty_adjustment": "same",
        "reason": "",
        "category": category,
        "profile_summary": _profile_summary(profile),
    }

    # 정상 상대 등 훈련 위험 신호가 없는 경우 — 깔끔하게 빈 선택
    if not candidates:
        base["reason"] = "정상 상대 시나리오 — 위험 신호 훈련 없이 '과한 의심'을 피하는 연습."
        return base

    rnd = random.Random()
    history_count = profile["history_count"]
    min_history = max(0, settings.adaptive_min_history_for_personalization)

    # --- 규칙 1: 히스토리 부족 → 균형 기본 선택 (가벼운 무작위) ---
    if history_count < min_history:
        rnd.shuffle(candidates)
        chosen = candidates[:max(1, limit)]
        base["selected_patterns"] = [b for b in (_pattern_brief(k) for k in chosen) if b]
        base["difficulty_adjustment"] = "same"
        base["reason"] = (
            f"초기 학습 단계({history_count}/{min_history}회) — 균형 잡힌 기본 시나리오로 시작합니다."
        )
        return base

    # --- 개인화: 우선순위 + 회피 + 무작위성 ---
    memory = {m["pattern_key"]: m for m in repo.get_training_memory(conn, user_id, role)}
    now = datetime.now(timezone.utc)

    avoided, scored = [], []
    for pk in candidates:
        mem = memory.get(pk)
        if _is_avoided(mem, now):
            avoided.append(pk)
            continue
        # 우선순위: 경험한 패턴은 메모리값(약점일수록 높음), 미경험은 0.45 로 노출 장려.
        # 작은 무작위(±0.05)로 변주를 주되, 약점 패턴(priority≳0.6)은 미경험(상한 0.50)을 앞선다.
        priority = float(mem["priority_score"]) if mem else 0.45
        jitter = rnd.uniform(-0.05, 0.05)
        scored.append((priority + jitter, pk))

    # 회피로 후보가 비면, 회피 목록에서라도 복습용으로 하나 되살린다 (게임이 비지 않도록)
    if not scored and avoided:
        revived = avoided[:max(1, limit)]
        base["selected_patterns"] = [b for b in (_pattern_brief(k) for k in revived) if b]
        base["avoided_patterns"] = []
        base["difficulty_adjustment"] = recommended_adj
        base["reason"] = "최근 잘 다룬 신호들 — 가볍게 복습합니다."
        return base

    scored.sort(key=lambda t: t[0], reverse=True)
    chosen_keys = [pk for _, pk in scored[:max(1, limit)]]

    base["selected_patterns"] = [b for b in (_pattern_brief(k) for k in chosen_keys) if b]
    base["avoided_patterns"] = [
        b for b in (taxonomy.public_pattern_card(k) for k in avoided) if b
    ]
    base["difficulty_adjustment"] = recommended_adj

    weak_labels = [
        taxonomy.get_pattern(k)["label"]
        for k in chosen_keys
        if k in profile["weak_patterns"] and taxonomy.get_pattern(k)
    ]
    if weak_labels:
        base["reason"] = (
            "약한 위험 신호를 우선 훈련합니다: " + ", ".join(weak_labels[:3]) + "."
        )
    else:
        base["reason"] = "다양성을 위해 패턴을 섞고, 숙달·최근 반복된 신호는 잠시 피했습니다."
    return base


def _profile_summary(profile: dict) -> dict:
    """선택 설명에 곁들이는 가벼운 요약 (서버 전용 — 라우터가 노출 여부 결정)."""
    return {
        "history_count": profile["history_count"],
        "avg_mastery": profile["avg_mastery"],
        "weak_count": len(profile["weak_patterns"]),
        "mastered_count": len(profile["mastered_patterns"]),
        "recommended_difficulty": profile["recommended_difficulty"],
    }
