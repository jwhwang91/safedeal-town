"""
안전한 '방어 훈련 패턴 분류표' (Adaptive defensive marketplace training taxonomy).

⚠️ 이 파일은 사기를 가르치지 않는다. 중고거래에서 '조심해야 할 위험 신호'를 학습 단위로
정의해, 사용자가 약한 신호를 더 자주 훈련하도록 커리큘럼을 똑똑하게 고르는 데만 쓴다.

각 패턴은:
  - pattern_key            : 전역 고유 키 (메모리/스냅샷의 식별자)
  - pattern_family         : 묶음(가족) — 비슷한 위험 신호를 한 갈래로
  - game_role              : 'buyer' | 'seller' (이 패턴이 훈련되는 모드)
  - label                  : 화면/리포트용 한국어 라벨
  - red_flag               : 대화에서 드러나는 위험 신호 (빈 문자열이면 '위험'이 아닌 학습 케이스)
  - safe_counter           : 사용자가 했어야 할 안전한 대응(교육용 일반 가이드)
  - severity               : 1~5 (높을수록 위험/중요)
  - allowed_simulation_style : 시뮬레이션에서 '허용'되는 연출(추상적·비실행적 묘사만)
  - forbidden_details      : 절대 생성하면 안 되는 실행적 사기 디테일 (안전 가드)

설계 원칙:
  - 이 분류표는 '정답 라벨'을 바꾸지 않는다. 규칙기반 JudgeAgent 가 여전히 권위.
  - 내부 tactic/behavior id(personas.py)와 분류표 pattern_key 를 매핑해, 한 대화에서
    실제로 등장한 위험 신호를 규칙기반으로 추출한다 (LLM 이 정답을 정하지 못하게).
"""
from __future__ import annotations

# 모든 패턴이 공유하는 '금지 디테일' — 어떤 제공자도 이걸 생성하면 안 된다.
# (분류표가 곧 안전 경계를 명시한다. persona_variant 검증기도 이 정신을 공유한다.)
_BASE_FORBIDDEN = [
    "real fake payment page setup",
    "credential or password collection",
    "real or working URLs",
    "bank account or card numbers",
    "platform detection bypass steps",
    "operational fraud procedure",
    "violent threats or harassment",
]


def _buyer(pattern_key, pattern_family, label, red_flag, safe_counter, severity,
           allowed_simulation_style, extra_forbidden=None):
    return {
        "pattern_key": pattern_key,
        "pattern_family": pattern_family,
        "game_role": "buyer",
        "label": label,
        "red_flag": red_flag,
        "safe_counter": safe_counter,
        "severity": severity,
        "allowed_simulation_style": allowed_simulation_style,
        "forbidden_details": list(_BASE_FORBIDDEN) + list(extra_forbidden or []),
    }


def _seller(pattern_key, pattern_family, label, red_flag, safe_counter, severity,
            allowed_simulation_style, extra_forbidden=None):
    return {
        "pattern_key": pattern_key,
        "pattern_family": pattern_family,
        "game_role": "seller",
        "label": label,
        "red_flag": red_flag,
        "safe_counter": safe_counter,
        "severity": severity,
        "allowed_simulation_style": allowed_simulation_style,
        "forbidden_details": list(_BASE_FORBIDDEN) + list(extra_forbidden or []),
    }


# ============================================================
#  구매자 모드 패턴 (사기 '판매자'를 가려내는 훈련)
# ============================================================
BUYER_PATTERNS: list[dict] = [
    _buyer(
        "buyer_low_price_lure", "price_anomaly", "초저가 미끼",
        "시세 대비 가격이 지나치게 낮음",
        "왜 이렇게 싼지 이유를 묻고, 시세와 꼼꼼히 비교한다.",
        3, ["시세보다 한참 싸다고 강조한다", "급해서 싸게 준다고 말한다"],
    ),
    _buyer(
        "buyer_urgency_pressure", "urgency_pressure", "시간 압박",
        "결정을 재촉하고 서두르게 만듦",
        "급할수록 멈춘다. 재촉당하는 것 자체를 의심한다.",
        3, ["'오늘만'·'문의 많다'며 서두르게 한다", "곧 마감이라고 압박한다"],
    ),
    _buyer(
        "buyer_verification_avoidance", "verification_avoidance", "검증 회피",
        "실물 사진·직거래·안전결제 등 정상 검증을 자꾸 피함",
        "사진·실물·안전결제 검증에 협조하지 않으면 거래를 보류한다.",
        4, ["사진 요청을 이런저런 핑계로 미룬다", "직거래 확인을 회피한다"],
    ),
    _buyer(
        "buyer_off_platform_link", "off_platform_migration", "외부 링크 유도",
        "앱 밖 링크나 외부 결제 페이지로 이동을 유도함",
        "앱 안 공식 기능 외 링크는 누르지 않고 거래를 중단하거나 플랫폼 신고를 검토한다.",
        5, ["상대가 외부 링크를 언급한다", "앱 안 결제가 불편하다고 말한다",
            "외부 절차가 더 빠르다고 주장한다"],
    ),
    _buyer(
        "buyer_prepayment_request", "prepayment_pressure", "선입금 요구",
        "물건 확인 전 입금을 먼저 요구",
        "물건 확인 전 선입금 요구가 나오면 거래를 중단한다.",
        5, ["물건을 받기 전에 입금부터 하라고 한다", "입금하면 바로 보내준다고 한다"],
    ),
    _buyer(
        "buyer_reservation_fee", "prepayment_pressure", "예약금·홀드비",
        "약속 전에 소액이라도 먼저 보내라고 함",
        "예약금·홀드비 명목의 선입금은 금액이 작아도 거절한다.",
        4, ["소액만 먼저 보내면 잡아준다고 한다", "예약금으로 다른 사람에게 안 넘긴다고 한다"],
    ),
    _buyer(
        "buyer_third_party_account", "third_party_identity_mismatch", "제3자 계좌",
        "물건 주인과 입금 계좌 명의가 다름",
        "계좌 명의가 대화 상대와 다르면 거래하지 않는다.",
        5, ["본인 계좌가 막혔다며 다른 명의 계좌를 언급한다"],
    ),
    _buyer(
        "buyer_platform_impersonation", "fake_safety_claim", "안전결제 사칭",
        "공식 안전결제인 척하지만 앱 밖 절차로 안심시킴",
        "결제는 무조건 앱 안 공식 기능으로만. 사칭이 의심되면 멈춘다.",
        5, ["자기만의 '안전결제'가 있다고 안심시킨다", "공식 절차처럼 들리게 포장한다"],
    ),
    _buyer(
        "buyer_shipping_pivot", "late_stage_fee_or_shipping_pressure", "택배 전환",
        "직거래 제안이 갑자기 택배(비대면)로 바뀜",
        "직거래 의사를 끝까지 확인하거나, 안 되면 안전결제를 고집한다.",
        3, ["직거래 하자더니 일정 핑계로 택배로 바꾼다"],
    ),
    _buyer(
        "buyer_delivery_fee_link", "late_stage_fee_or_shipping_pressure", "택배비·송장 링크",
        "거래 막판에 택배·환불·송장 명목의 링크/추가비용을 들이밂",
        "거래 끝물에 들어오는 링크·추가비용일수록 더 의심한다.",
        4, ["거의 끝났다는 안도감에 택배비·송장 확인을 끼워 넣는다"],
    ),
    _buyer(
        "buyer_trust_building", "overtrust_social_proof", "과한 신뢰 쌓기",
        "지나치게 매끄럽고 친절해서 의심을 덜 하게 만듦",
        "친절함은 신뢰의 근거가 아니다. 검증 절차는 그대로 지킨다.",
        2, ["친절·후기·매끄러운 절차로 경계심을 먼저 푼다"],
    ),
    _buyer(
        "buyer_condition_inconsistency", "inconsistency_in_item_condition", "상태 설명 불일치",
        "물건 상태·구성품 설명이 말할 때마다 달라짐",
        "설명이 오락가락하면 실물·사진으로 다시 확인하고 안 맞으면 보류한다.",
        3, ["상태·구성품 설명이 앞뒤가 안 맞는다"],
    ),
]


# ============================================================
#  판매자 모드 패턴 (진상·위험 '구매자'에 안전하게 대응하는 훈련)
# ============================================================
SELLER_PATTERNS: list[dict] = [
    _seller(
        "seller_ignore_disclosure", "condition_dispute_after_disclosure", "고지 무시 환불 요구",
        "판매 전 고지한 하자를 못 들은 척하며 환불을 요구함",
        "판매 전 고지 기록과 사진을 근거로 차분히 설명하고, 필요하면 플랫폼 분쟁 절차로 넘긴다.",
        4, ["구매자가 기존 고지 내용을 부정한다", "감정적으로 환불을 요구한다",
            "나쁜 후기를 암시한다"],
        extra_forbidden=["legal certainty", "threat escalation", "retaliation instructions"],
    ),
    _seller(
        "seller_self_inflicted_damage", "condition_dispute_after_disclosure", "본인 과실 전가",
        "수령 후 생긴 손상을 처음부터 불량이었다고 우김",
        "발송 전 상태 사진·영상 기록을 제시한다. 단정 짓지 말고 증거로 말한다.",
        3, ["받은 뒤 생긴 문제를 판매자 책임으로 돌린다"],
        extra_forbidden=["legal certainty", "retaliation instructions"],
    ),
    _seller(
        "seller_unreasonable_refund", "unreasonable_refund_pressure", "부당 환불 요구",
        "정상적으로 확인하고 산 물건을 근거 없이 전액 환불 요구",
        "감정에 휘말리지 말고 거래 당시 고지·합의를 근거로 정중히 거절하거나 플랫폼 분쟁으로 넘긴다.",
        4, ["사용·시간이 지났는데 막무가내로 전액 환불을 요구한다"],
        extra_forbidden=["legal certainty", "threat escalation"],
    ),
    _seller(
        "seller_guilt_trip", "emotional_manipulation", "감정 호소",
        "동정심을 이용해 합리적 선을 넘는 요구",
        "공감은 하되 기준은 지킨다. 측은함과 거래 책임은 분리해서 판단한다.",
        2, ["딱한 사정으로 무리한 요구를 관철하려 한다"],
    ),
    _seller(
        "seller_review_threat", "bad_review_threat", "후기 협박",
        "정당한 사유 없이 악의적 후기로 협박",
        "협박에 굴해 환불하지 말고, 협박 메시지를 캡처해 플랫폼에 신고한다.",
        4, ["별점 테러·나쁜 후기를 암시하며 환불을 압박한다"],
        extra_forbidden=["harassment", "threat escalation"],
    ),
    _seller(
        "seller_report_threat", "false_legal_threat", "신고·고소 협박",
        "법적 근거 없이 신고/고소로 위협",
        "맞협박하지 말고 침착하게. 정당한 거래였다면 기록을 근거로 플랫폼 분쟁 절차를 안내한다.",
        4, ["근거 없이 경찰 신고·고소를 운운한다"],
        extra_forbidden=["legal certainty", "threat escalation", "harassment"],
    ),
    _seller(
        "seller_off_platform_pay", "off_platform_payment_pressure", "외부 결제 유도",
        "플랫폼 밖 직접 송금을 권유",
        "거래·결제는 플랫폼 안전결제/공식 기능으로만. 외부 결제는 거절한다.",
        4, ["수수료·편의를 핑계로 플랫폼 밖 송금을 권한다"],
    ),
    _seller(
        "seller_risky_pickup", "pickup_or_delivery_boundary_violation", "위험한 직거래",
        "안전하지 않은 장소·방식의 만남을 요구",
        "공공장소·낮 시간 직거래를 제안하고, 불응하면 거래하지 않는다.",
        4, ["인적 드문 곳·심야·대리수령 등 이상한 직거래를 요구한다"],
    ),
    _seller(
        "seller_excessive_lowball", "excessive_lowballing", "과도한 후려치기",
        "비상식적으로 낮은 가격을 끈질기게 요구",
        "원하는 가격선을 분명히 정하고, 안 맞으면 정중히 거래를 정리한다.",
        2, ["시세를 무시한 헐값을 반복해서 들이민다"],
    ),
    _seller(
        "seller_ghosting", "ghosting_after_commitment", "잠수",
        "구매 의사 없이 시간만 끌다 사라짐",
        "재촉하지 말고 다음 구매자를 받는다. 약속·예약은 기록으로 남긴다.",
        1, ["질문만 잔뜩 하고 결정 직전에 답이 끊긴다"],
    ),
    _seller(
        "seller_legit_defect_claim", "legitimate_buyer_complaint", "정당한 하자 주장",
        "",  # 빈 값 = 위험신호가 아님. 판매자가 '잘 해결해야 하는' 정당한 케이스.
        "고지를 빠뜨린 진짜 하자라면 발뺌하지 말고 부분환불/환불/플랫폼 절차로 합리적으로 해결한다.",
        2, ["고지되지 않은 진짜 하자를 정중하게 알리고 합리적 해결을 요청한다"],
    ),
]


ALL_PATTERNS: list[dict] = BUYER_PATTERNS + SELLER_PATTERNS

# pattern_key → 패턴 dict
PATTERNS_BY_KEY: dict[str, dict] = {p["pattern_key"]: p for p in ALL_PATTERNS}


# ============================================================
#  내부 tactic/behavior id ↔ 분류표 pattern_key 매핑
# ============================================================
# personas.py 의 TACTICS(구매자 모드 판매자 수법) → 분류표 키
TACTIC_TO_PATTERN_KEY: dict[str, str] = {
    "low_price_lure": "buyer_low_price_lure",
    "urgency": "buyer_urgency_pressure",
    "shipping_pivot": "buyer_shipping_pivot",
    "prepayment_request": "buyer_prepayment_request",
    "reservation_fee": "buyer_reservation_fee",
    "platform_impersonation": "buyer_platform_impersonation",
    "off_platform_link": "buyer_off_platform_link",
    "delivery_fee_link": "buyer_delivery_fee_link",
    "third_party_account": "buyer_third_party_account",
    "trust_building": "buyer_trust_building",
}

# personas.py 의 BUYER_BEHAVIORS(판매자 모드 구매자 행동) → 분류표 키
# (normal_inquiry 는 위험/학습 패턴이 아니므로 의도적으로 매핑하지 않는다.)
BEHAVIOR_TO_PATTERN_KEY: dict[str, str] = {
    "ignore_disclosure": "seller_ignore_disclosure",
    "self_inflicted_damage": "seller_self_inflicted_damage",
    "unreasonable_refund": "seller_unreasonable_refund",
    "guilt_trip": "seller_guilt_trip",
    "review_threat": "seller_review_threat",
    "report_threat": "seller_report_threat",
    "off_platform_pay": "seller_off_platform_pay",
    "risky_pickup": "seller_risky_pickup",
    "excessive_lowball": "seller_excessive_lowball",
    "ghosting": "seller_ghosting",
    "legit_defect_claim": "seller_legit_defect_claim",
}


def pattern_key_for_label(internal_id: str, game_role: str) -> str | None:
    """대화 메시지에 저장된 내부 tactic/behavior id → 분류표 pattern_key.

    game_role 로 어느 매핑을 쓸지 고른다. 매핑이 없으면(중립 행동 등) None.
    """
    if not internal_id or internal_id == "none":
        return None
    if game_role == "seller":
        return BEHAVIOR_TO_PATTERN_KEY.get(internal_id)
    return TACTIC_TO_PATTERN_KEY.get(internal_id)


def get_pattern(pattern_key: str) -> dict | None:
    return PATTERNS_BY_KEY.get(pattern_key)


def patterns_for_role(game_role: str) -> list[dict]:
    role = "seller" if game_role == "seller" else "buyer"
    return [p for p in ALL_PATTERNS if p["game_role"] == role]


def public_pattern_card(pattern_key: str) -> dict | None:
    """프론트로 내려보내도 안전한 라벨/대응만 추린다 (내부 키·금지목록 제외)."""
    p = PATTERNS_BY_KEY.get(pattern_key)
    if not p:
        return None
    return {
        "label": p["label"],
        "red_flag": p["red_flag"],
        "safe_counter": p["safe_counter"],
        "pattern_family": p["pattern_family"],
        "severity": p["severity"],
    }


def is_risk_pattern(pattern_key: str) -> bool:
    """red_flag 가 있는 '위험 신호' 패턴인지 (정당한 하자 주장 등은 위험이 아님)."""
    p = PATTERNS_BY_KEY.get(pattern_key)
    return bool(p and p.get("red_flag"))


# ============================================================
#  상대 종류(counterparty_kind) 정규화
# ============================================================
# 구매자 모드: 판매자 NPC role / role_type → 표준 상대 종류
_SELLER_KIND_BY_ROLE_TYPE = {
    "scam_smooth": "scam_seller",
    "scam_impatient": "scam_seller",
    "scam_pro": "scam_seller",
    "honest_seller": "honest_seller",
    "rude_but_honest_seller": "rude_but_honest_seller",
    "professional_seller": "professional_seller",
    "newbie_seller": "honest_seller",
}
# 판매자 모드: 구매자 NPC role → 표준 상대 종류
_BUYER_KIND_BY_ROLE = {
    "honest_buyer": "honest_buyer",
    "refund_villain": "refund_villain",
    "lowballer": "lowballer",
    "ghosting_buyer": "ghosting_buyer",
    "risky_buyer": "risky_buyer",
    "legit_claim_buyer": "legitimate_claim_buyer",
}


def counterparty_kind_for(npc: dict) -> str:
    """NPC 의 (서버 전용) 정답 역할 → 안전 분석용 상대 종류 라벨."""
    if npc.get("npc_kind") == "buyer":  # 판매자 모드 상대
        return _BUYER_KIND_BY_ROLE.get(npc.get("role"), "honest_buyer")
    # 구매자 모드 상대(판매자 NPC)
    role_type = npc.get("role_type")
    if role_type and role_type in _SELLER_KIND_BY_ROLE_TYPE:
        return _SELLER_KIND_BY_ROLE_TYPE[role_type]
    return "scam_seller" if npc.get("role") == "scammer" else "honest_seller"
