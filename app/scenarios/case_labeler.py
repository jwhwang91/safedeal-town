"""
커뮤니티 사례 → 라벨 추출 (규칙 기반, LLM 없음).

비식별된 사례 본문 + 비식별 단계가 준 위험 신호(risk_signals)를 근거로,
'어떤 위험군(risk_family)인지 / 어떤 압박·요구였는지 / 안전한 대응은 무엇인지 /
어떤 훈련 모듈로 연결되는지'를 키워드 규칙으로 추론한다.

⚠️ 이 모듈은 '정답 라벨'을 확정하지 않는다. 방어 훈련 자료 분류를 돕는 힌트일 뿐이며,
   각 라벨에 대략적인 confidence(0~1) 를 함께 돌려준다. 실패해도 앱은 계속 동작한다.

canonical risk_family (위험군):
  off_platform_link, personal_contact_grooming, voice_call_pressure,
  romance_boundary_pressure, delivery_payment_risk, fake_safe_payment,
  job_offer_scam, investment_pressure, account_takeover, refund_conflict
"""
from __future__ import annotations

# ------------------------------------------------------------
#  위험군별 키워드 (비식별 본문에서 탐지) — 방어 관점의 표지어
# ------------------------------------------------------------
_FAMILY_KEYWORDS: dict[str, list[str]] = {
    "fake_safe_payment": [
        "안전결제", "안전거래", "가짜 안전", "안전결제 사이트", "안전결제 링크",
    ],
    "off_platform_link": [
        "링크", "외부 사이트", "사이트 접속", "결제창", "설치", "앱 밖",
        "외부 결제", "url", "주소로 접속",
    ],
    "personal_contact_grooming": [
        "카톡", "카카오", "텔레그램", "텔레", "라인", "오픈채팅", "친구 추가",
        "개인 연락", "번호 알려", "번호 주", "따로 연락",
    ],
    "voice_call_pressure": [
        "전화", "통화", "본인확인", "인증번호", "고객센터", "상담원",
        "검찰", "경찰", "금융감독원", "금감원", "수사", "명의가 도용",
    ],
    "romance_boundary_pressure": [
        "애인", "사랑", "연인", "소개팅", "데이트", "외로", "호감",
        "만나자", "선물", "사귀", "썸",
    ],
    "delivery_payment_risk": [
        "택배", "선입금", "예약금", "입금", "배송", "송장", "계좌로",
        "먼저 보내", "먼저 입금", "물건 빼둔",
    ],
    "job_offer_scam": [
        "알바", "부업", "재택", "채용", "구인", "일자리", "수수료 먼저",
        "가입비", "일당", "고수익 알바",
    ],
    "investment_pressure": [
        "투자", "코인", "리딩", "수익", "원금 보장", "종목", "주식 리딩방",
        "확정 수익", "배당",
    ],
    "account_takeover": [
        "계정", "비밀번호", "로그인", "해킹", "명의도용", "otp",
        "인증서", "가로채", "탈취",
    ],
    "refund_conflict": [
        "환불", "반품", "하자", "고장", "교환", "책임", "돌려", "불량",
        "악평", "별점", "신고하겠",
    ],
}

# 비식별 단계 risk_signals → 위험군 가중치 힌트
_SIGNAL_TO_FAMILIES: dict[str, list[str]] = {
    "external_link": ["off_platform_link", "fake_safe_payment"],
    "private_contact": ["personal_contact_grooming"],
    "off_platform_contact": ["personal_contact_grooming", "voice_call_pressure"],
    "account_transfer": ["delivery_payment_risk", "fake_safe_payment"],
    "identity_exposure": ["account_takeover", "voice_call_pressure"],
    "credential_exposure": ["account_takeover"],
}

# 카테고리 → 기본 위험군 (아무 키워드도 안 걸릴 때의 폴백)
_CATEGORY_TO_FAMILY: dict[str, str] = {
    "used_marketplace": "off_platform_link",
    "voice_phishing": "voice_call_pressure",
    "romance_scam": "romance_boundary_pressure",
    "side_job_scam": "job_offer_scam",
    "job_scam": "job_offer_scam",
    "investment_scam": "investment_pressure",
    "account_takeover": "account_takeover",
    "private_contact_boundary": "personal_contact_grooming",
    "seller_refund_conflict": "refund_conflict",
    "delivery_trade_safety": "delivery_payment_risk",
}

# 위험군 → 기본 카테고리 (카테고리 미제공 시 채움)
_FAMILY_TO_CATEGORY: dict[str, str] = {
    "off_platform_link": "used_marketplace",
    "fake_safe_payment": "used_marketplace",
    "delivery_payment_risk": "delivery_trade_safety",
    "personal_contact_grooming": "private_contact_boundary",
    "voice_call_pressure": "voice_phishing",
    "romance_boundary_pressure": "romance_scam",
    "job_offer_scam": "job_scam",
    "investment_pressure": "investment_scam",
    "account_takeover": "account_takeover",
    "refund_conflict": "seller_refund_conflict",
}

# 위험군 → 훈련 모듈(미션 키 힌트 또는 위험 차원 키)
_FAMILY_TO_MODULE: dict[str, str] = {
    "off_platform_link": "safe_payment_buyer",
    "fake_safe_payment": "safe_payment_buyer",
    "delivery_payment_risk": "delivery_only_buyer",
    "personal_contact_grooming": "boundary_keeper_buyer",
    "voice_call_pressure": "voice_phishing_like_pressure",
    "romance_boundary_pressure": "boundary_keeper_buyer",
    "job_offer_scam": "off_platform_link_detection",
    "investment_pressure": "urgency_pressure_resistance",
    "account_takeover": "voice_phishing_like_pressure",
    "refund_conflict": "refund_boundary_seller",
}

# 위험군 → 대표 '요구된 행동' (사기꾼이 유도한 것)
_FAMILY_TO_REQUESTED_ACTION: dict[str, str] = {
    "off_platform_link": "앱 밖 외부 링크 접속·결제 유도",
    "fake_safe_payment": "가짜 안전결제 페이지에서 결제/정보 입력 유도",
    "delivery_payment_risk": "실물 확인 전 선입금·계좌 이체 요구",
    "personal_contact_grooming": "앱 밖 개인 연락으로 이동 유도",
    "voice_call_pressure": "전화 통화·외부 인증·인증번호 요구",
    "romance_boundary_pressure": "친밀감을 앞세운 금전·신뢰 요구",
    "job_offer_scam": "선수수료·가입비 등 먼저 입금 요구",
    "investment_pressure": "고수익을 미끼로 빠른 투자 결정 요구",
    "account_takeover": "계정·인증정보·비밀번호 요구",
    "refund_conflict": "근거 없는 환불·책임 전가 압박",
}

# 위험군 → 안전한 대응(요약)
_FAMILY_TO_SAFE_RESPONSE: dict[str, str] = {
    "off_platform_link": "외부 링크는 누르지 않고 앱 내 공식 절차만 쓴다",
    "fake_safe_payment": "안전결제는 앱 내 공식 기능으로만 확인한다",
    "delivery_payment_risk": "확인 전 입금을 거절하고 안전결제·실물 인증을 요청한다",
    "personal_contact_grooming": "거래 대화는 앱 안에서만, 개인 연락 유도는 단호히 거절한다",
    "voice_call_pressure": "전화·외부 인증은 공식 채널로만 확인하고 인증번호는 알려주지 않는다",
    "romance_boundary_pressure": "감정과 거래 판단을 분리하고 금전이 얽히면 멈춘다",
    "job_offer_scam": "먼저 입금·가입비 요구는 거절하고 정식 채용 절차만 신뢰한다",
    "investment_pressure": "확정 수익 약속과 재촉은 위험 신호로 보고 독립적으로 확인한다",
    "account_takeover": "인증정보·비밀번호는 누구에게도 알려주지 않는다",
    "refund_conflict": "감정 대신 고지·기록을 근거로 침착하게 대응한다",
}

# 압박 유형 표지어
_URGENCY_WORDS = ["지금", "오늘만", "빨리", "당장", "마감", "곧", "서둘", "품절", "선착순"]
_AUTHORITY_WORDS = ["검찰", "경찰", "금감원", "금융감독원", "수사", "고객센터", "공식"]
_EMOTIONAL_WORDS = ["사랑", "믿어", "우리 사이", "외로", "호감", "서운", "정"]
_GREED_WORDS = ["고수익", "확정 수익", "원금 보장", "대박", "공짜", "특가", "이득"]


def _normalize_signals(risk_signals) -> list[str]:
    """risk_signals 가 문자열 리스트든 딕트 리스트든 문자열 리스트로 정규화."""
    out: list[str] = []
    if not risk_signals:
        return out
    try:
        for s in risk_signals:
            if isinstance(s, str):
                out.append(s)
            elif isinstance(s, dict):
                v = s.get("flag") or s.get("signal") or s.get("type") or s.get("key")
                if isinstance(v, str):
                    out.append(v)
    except Exception:
        pass
    return out


def _pressure_type(body: str, family: str) -> str:
    """압박 유형 추론: authority | emotional | greed | urgency | none."""
    if any(w in body for w in _AUTHORITY_WORDS) or family == "voice_call_pressure":
        return "authority"
    if any(w in body for w in _EMOTIONAL_WORDS) or family == "romance_boundary_pressure":
        return "emotional"
    if any(w in body for w in _GREED_WORDS) or family in (
        "investment_pressure", "job_offer_scam",
    ):
        return "greed"
    if any(w in body for w in _URGENCY_WORDS):
        return "urgency"
    return "none"


def extract_case_labels(redacted_case: dict) -> dict:
    """비식별 사례에서 라벨을 규칙 기반으로 추출한다.

    입력(redacted_case) 예:
      {category, redacted_body, platform, risk_signals:[...]}

    반환:
      {
        "labels": {category, platform, scam_type, risk_family, pressure_type,
                   requested_action, safe_response, training_module},
        "confidence": {label_key: 0..1},
        "risk_family": str,
        "category": str,
      }
    """
    case = redacted_case or {}
    body = str(case.get("redacted_body") or "").lower()
    platform = str(case.get("platform") or "").strip()
    given_category = str(case.get("category") or "").strip()
    signals = _normalize_signals(case.get("risk_signals"))

    # 1) 위험군 점수 계산 (키워드 히트 + 신호 가중치)
    scores: dict[str, float] = {fam: 0.0 for fam in _FAMILY_KEYWORDS}
    for fam, words in _FAMILY_KEYWORDS.items():
        for w in words:
            if w.lower() in body:
                scores[fam] += 1.0
    for sig in signals:
        for fam in _SIGNAL_TO_FAMILIES.get(sig, []):
            scores[fam] += 1.5

    best_family = max(scores, key=lambda k: scores[k]) if scores else ""
    best_score = scores.get(best_family, 0.0)

    # 아무것도 안 걸리면 카테고리 폴백
    if best_score <= 0.0:
        best_family = _CATEGORY_TO_FAMILY.get(given_category, "off_platform_link")
        family_conf = 0.3
    else:
        # 점수가 클수록 신뢰↑ (상한 0.95)
        family_conf = min(0.95, 0.45 + 0.15 * best_score)

    # 2) 카테고리 확정 (없으면 위험군에서 도출)
    category = given_category or _FAMILY_TO_CATEGORY.get(best_family, "used_marketplace")
    category_conf = 0.9 if given_category else 0.5

    pressure = _pressure_type(body, best_family)
    pressure_conf = 0.7 if pressure != "none" else 0.4

    requested_action = _FAMILY_TO_REQUESTED_ACTION.get(
        best_family, "정식 절차를 건너뛰도록 유도"
    )
    safe_response = _FAMILY_TO_SAFE_RESPONSE.get(
        best_family, "정식 절차만 따르고, 이상하면 멈추고 확인한다"
    )
    training_module = _FAMILY_TO_MODULE.get(best_family, "off_platform_link_detection")

    labels = {
        "category": category,
        "platform": platform or "unknown",
        "scam_type": best_family,          # 위험군을 scam_type 으로도 노출
        "risk_family": best_family,
        "pressure_type": pressure,
        "requested_action": requested_action,
        "safe_response": safe_response,
        "training_module": training_module,
    }
    confidence = {
        "category": round(category_conf, 2),
        "platform": 0.9 if platform else 0.2,
        "scam_type": round(family_conf, 2),
        "risk_family": round(family_conf, 2),
        "pressure_type": round(pressure_conf, 2),
        "requested_action": round(family_conf, 2),
        "safe_response": round(family_conf, 2),
        "training_module": round(family_conf, 2),
    }

    return {
        "labels": labels,
        "confidence": confidence,
        "risk_family": best_family,
        "category": category,
    }
