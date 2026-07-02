"""
위험 차원(risk dimension) 레지스트리 + 점수 계산 규칙.

⚠️ 이 모듈은 '사기를 더 잘하는 법'을 다루지 않는다. 사용자가 '어떤 위험 신호에 약한지'를
투명하게 측정해, 방어 훈련을 개인화하기 위한 채점 규칙만 정의한다.

이 파일은 플랫폼 레이어 전체의 '의미 계약(contract)'이다:
  - 진단 문항(assessment)의 risk_family 는 여기 정의된 DIMENSION_KEYS 중 하나다.
  - 게임/미션/부정행위 신호를 같은 차원으로 환산해 통합 프로필을 만든다.
  - 리포트는 이 레지스트리의 라벨/추천 훈련 문구를 그대로 노출한다.

점수 관례(중요):
  - dimension score 는 0~100 이며 '높을수록 안전/강함'(= 방어 역량)이다.
  - overall_risk_score 도 동일하게 '높을수록 잘 방어함'을 뜻한다.
    (사기 위험이 높다는 뜻이 아니라, 방어 훈련 점수임 — 리포트에서 명시한다.)
  - 이 점수는 의료/법률/공식 진단이 아니라 '훈련용 데모 점수'다.
"""
from __future__ import annotations

# ------------------------------------------------------------
#  15개 위험 차원 (일관된 key — 서버/클라이언트/리포트 공용)
# ------------------------------------------------------------
# 각 차원:
#   key                : 전역 고유 키 (진단 risk_family / 프로필 / 리포트 공용)
#   label              : 화면/리포트용 한국어 라벨
#   blurb              : 한 줄 설명
#   recommended_training : 약할 때 추천하는 방어 훈련 문구
#   mission_keys       : 이 차원을 훈련하는 미션 키(있으면) — 리포트 '다음 미션' 추천에 사용
RISK_DIMENSIONS: list[dict] = [
    {
        "key": "price_anomaly_detection",
        "label": "시세 이상 감지",
        "blurb": "지나치게 싼 값·급처분 미끼를 의심하는 능력",
        "recommended_training": "시세를 항상 비교하고, '왜 이렇게 싼지'를 먼저 묻는 훈련",
        "mission_keys": [],
    },
    {
        "key": "urgency_pressure_resistance",
        "label": "시간 압박 저항",
        "blurb": "'오늘만', '지금 바로' 같은 재촉에 흔들리지 않는 능력",
        "recommended_training": "재촉당할수록 결정을 미루고 한 박자 멈추는 훈련",
        "mission_keys": [],
    },
    {
        "key": "off_platform_link_detection",
        "label": "외부 링크 유도 감지",
        "blurb": "앱 밖 링크·외부 결제 페이지 유도를 알아채고 거절하는 능력",
        "recommended_training": "외부 링크는 누르지 않고 앱 내 공식 절차만 쓰는 훈련",
        "mission_keys": ["safe_payment_buyer"],
    },
    {
        "key": "prepayment_refusal",
        "label": "선입금 거절",
        "blurb": "물건 확인 전 선입금·예약금 요구를 거절하는 능력",
        "recommended_training": "확인 전 입금 요구는 금액이 작아도 거절하는 훈련",
        "mission_keys": ["safe_payment_buyer"],
    },
    {
        "key": "third_party_account_suspicion",
        "label": "제3자 계좌 의심",
        "blurb": "대화 상대와 입금 계좌 명의가 다를 때 멈추는 능력",
        "recommended_training": "계좌 명의와 판매자 신원이 일치하는지 확인하는 훈련",
        "mission_keys": [],
    },
    {
        "key": "safe_delivery_trade",
        "label": "안전한 택배거래",
        "blurb": "택배거래에서 실물 인증·안전 절차를 챙기는 능력",
        "recommended_training": "택배거래 전 실물/구성품 인증과 안전한 절차를 확인하는 훈련",
        "mission_keys": ["delivery_only_buyer", "delivery_safe_seller"],
    },
    {
        "key": "platform_chat_preservation",
        "label": "플랫폼 대화 유지",
        "blurb": "대화를 플랫폼 안에 남겨 증거를 보존하는 능력",
        "recommended_training": "거래 대화를 플랫폼 안에서만 이어가는 훈련",
        "mission_keys": ["boundary_keeper_buyer", "private_contact_refusal_seller"],
    },
    {
        "key": "personal_contact_boundary",
        "label": "개인 연락 경계",
        "blurb": "전화번호·메신저 교환 등 사적 연락 유도를 거절하는 능력",
        "recommended_training": "사적 연락 유도는 정중하지만 단호하게 거절하는 훈련",
        "mission_keys": ["boundary_keeper_buyer", "private_contact_refusal_seller"],
    },
    {
        "key": "voice_phishing_like_pressure",
        "label": "통화·인증 압박 대응",
        "blurb": "전화 본인확인·외부 인증 핑계 압박에 흔들리지 않는 능력",
        "recommended_training": "전화·외부 인증 요구는 공식 채널로만 확인하는 훈련",
        "mission_keys": [],
    },
    {
        "key": "romance_scam_boundary",
        "label": "감정 신뢰 조작 경계",
        "blurb": "호감·친밀감을 앞세운 접근에서 경계를 지키는 능력",
        "recommended_training": "감정적 신뢰가 거래 판단을 흐리지 않게 분리하는 훈련",
        "mission_keys": ["boundary_keeper_buyer"],
    },
    {
        "key": "refund_villain_response",
        "label": "부당 환불 요구 대응",
        "blurb": "근거 없는 환불 요구에 기록 중심으로 대응하는 능력",
        "recommended_training": "환불 요구엔 감정 대신 고지·기록을 근거로 대응하는 훈련",
        "mission_keys": ["refund_boundary_seller"],
    },
    {
        "key": "seller_misconduct_avoidance",
        "label": "판매자 부정행위 회피",
        "blurb": "판매자로서 욕설·협박·과실 전가 같은 부적절 대응을 피하는 능력",
        "recommended_training": "불리한 상황에서도 침착하고 정직하게 대응하는 훈련",
        "mission_keys": ["lowball_boundary_seller"],
    },
    {
        "key": "evidence_based_response",
        "label": "증거 중심 대응",
        "blurb": "실물 인증·상태 기록 등 증거를 확보하고 근거로 판단하는 능력",
        "recommended_training": "판단 전 실물/날짜/구성품 인증을 요청하는 훈련",
        "mission_keys": ["proof_first_buyer", "refund_boundary_seller"],
    },
    {
        "key": "calm_dispute_handling",
        "label": "침착한 분쟁 대응",
        "blurb": "협박·막깎이·감정 호소에 침착하게 기준을 지키는 능력",
        "recommended_training": "압박에도 감정적으로 반응하지 않고 기준선을 지키는 훈련",
        "mission_keys": ["lowball_boundary_seller"],
    },
    {
        "key": "legitimate_claim_recognition",
        "label": "정당한 요구 인정",
        "blurb": "정당한 하자 주장·환불 요구를 무조건 거절하지 않고 알아보는 능력",
        "recommended_training": "정당한 하자 주장인지 사실 기준으로 구분하는 훈련",
        "mission_keys": [],
    },
]

DIMENSION_KEYS: list[str] = [d["key"] for d in RISK_DIMENSIONS]
DIMENSIONS_BY_KEY: dict[str, dict] = {d["key"]: d for d in RISK_DIMENSIONS}


# ------------------------------------------------------------
#  진단 카테고리 (10종) → 기본 위험 차원 (문항 시드에서 참조)
# ------------------------------------------------------------
ASSESSMENT_CATEGORIES: list[str] = [
    "used_marketplace",
    "voice_phishing",
    "romance_scam",
    "side_job_scam",
    "job_scam",
    "investment_scam",
    "account_takeover",
    "private_contact_boundary",
    "seller_refund_conflict",
    "delivery_trade_safety",
]


# ------------------------------------------------------------
#  게임 taxonomy pattern_family → 위험 차원 매핑
#  (한 대화에서 규칙기반으로 추출된 패턴을 통합 프로필의 차원으로 환산)
# ------------------------------------------------------------
FAMILY_TO_DIMENSION: dict[str, str] = {
    # 구매자 모드
    "price_anomaly": "price_anomaly_detection",
    "urgency_pressure": "urgency_pressure_resistance",
    "verification_avoidance": "evidence_based_response",
    "off_platform_migration": "off_platform_link_detection",
    "prepayment_pressure": "prepayment_refusal",
    "third_party_identity_mismatch": "third_party_account_suspicion",
    "fake_safety_claim": "off_platform_link_detection",
    "late_stage_fee_or_shipping_pressure": "safe_delivery_trade",
    "overtrust_social_proof": "romance_scam_boundary",
    "inconsistency_in_item_condition": "evidence_based_response",
    "private_contact_pivot": "personal_contact_boundary",
    "romance_pressure": "romance_scam_boundary",
    "phishing_pretext": "voice_phishing_like_pressure",
    "voice_phishing": "voice_phishing_like_pressure",
    "emotional_trust_manipulation": "romance_scam_boundary",
    "social_engineering": "urgency_pressure_resistance",
    "harassment": "calm_dispute_handling",
    # 판매자 모드
    "condition_dispute_after_disclosure": "refund_villain_response",
    "unreasonable_refund_pressure": "refund_villain_response",
    "emotional_manipulation": "calm_dispute_handling",
    "bad_review_threat": "calm_dispute_handling",
    "false_legal_threat": "calm_dispute_handling",
    "off_platform_payment_pressure": "off_platform_link_detection",
    "pickup_or_delivery_boundary_violation": "safe_delivery_trade",
    "excessive_lowballing": "calm_dispute_handling",
    "ghosting_after_commitment": "seller_misconduct_avoidance",
    "legitimate_buyer_complaint": "legitimate_claim_recognition",
}


# ------------------------------------------------------------
#  미션 키 → 위험 차원 (미션 성공/실패를 차원 점수에 반영)
# ------------------------------------------------------------
MISSION_TO_DIMENSION: dict[str, str] = {
    "delivery_only_buyer": "safe_delivery_trade",
    "safe_payment_buyer": "off_platform_link_detection",
    "proof_first_buyer": "evidence_based_response",
    "boundary_keeper_buyer": "personal_contact_boundary",
    "delivery_safe_seller": "safe_delivery_trade",
    "refund_boundary_seller": "refund_villain_response",
    "private_contact_refusal_seller": "personal_contact_boundary",
    "lowball_boundary_seller": "calm_dispute_handling",
}


def dimension_for_family(pattern_family: str | None) -> str | None:
    """taxonomy pattern_family → 위험 차원 key (모르면 None)."""
    if not pattern_family:
        return None
    return FAMILY_TO_DIMENSION.get(pattern_family)


def dimension_for_mission(mission_key: str | None) -> str | None:
    if not mission_key:
        return None
    return MISSION_TO_DIMENSION.get(mission_key)


def dimension_meta(key: str) -> dict:
    """차원 메타(라벨/설명/추천 훈련). 모르는 key 면 key 자체를 라벨로 하는 안전 기본값."""
    return DIMENSIONS_BY_KEY.get(key) or {
        "key": key, "label": key, "blurb": "",
        "recommended_training": "", "mission_keys": [],
    }


# ------------------------------------------------------------
#  점수 헬퍼 (0~100, 높을수록 안전/강함)
# ------------------------------------------------------------
def level_for_score(score: int | float) -> str:
    """차원 점수 → 등급. weak(<40) | moderate(40~74) | strong(>=75)."""
    s = float(score)
    if s < 40:
        return "weak"
    if s < 75:
        return "moderate"
    return "strong"


def level_label_ko(level: str) -> str:
    return {"weak": "약함", "moderate": "보통", "strong": "강함"}.get(level, "보통")


def ratio_to_score(numerator: float, denominator: float, default: int = 50) -> int:
    """맞힌 비율 → 0~100 정수 점수. 데이터가 없으면 중립값(default)."""
    if denominator <= 0:
        return int(default)
    return int(round(100.0 * numerator / denominator))


def confidence_from_evidence(total_signals: int) -> str:
    """근거(진단문항+거래+미션 수) 총량 → 신뢰도 라벨.

    데모 성격을 분명히 하려고 'demo_' 접두를 붙인다.
    """
    if total_signals <= 0:
        return "demo_low"
    if total_signals < 6:
        return "demo_low"
    if total_signals < 16:
        return "demo_medium"
    return "demo_high"


# 프로필/리포트에 항상 붙이는 면책 문구 (의료/법률/공식 진단 아님)
DISCLAIMER = (
    "이 점수는 방어 훈련용 데모 지표예요. 의료·법률·공식 진단이 아니며, "
    "훈련 기록이 쌓일수록 정확해집니다."
)
