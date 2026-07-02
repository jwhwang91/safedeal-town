"""
사례 → 방어 시나리오 생성기 (템플릿 우선, LLM 은 선택·검증 필수).

원칙(안전):
  - 기본 제공자는 template(규칙 기반)이며 항상 오프라인·안전하다.
  - 커뮤니티 사례 본문을 절대 그대로 복제하지 않는다 — 위험군 템플릿으로 '일반화'한다.
  - provider 가 local_claude/openai 라도, 생성 초안은 반드시 validate 를 통과해야 채택된다.
    (필수 키 존재 / 계좌·URL·전화처럼 보이는 값 0건 / 사례 본문과 동일하지 않음)
    검증 실패·타임아웃·미구현이면 언제나 template 결과로 폴백한다 → 파이프라인은 멈추지 않는다.

반환 계약:
  generate_scenario_from_case(conn, case) ->
    {"scenario": <dict>, "provider_used": "template"|"local_claude"|"openai",
     "requires_review": bool}
"""
from __future__ import annotations

import sqlite3

from app.config import get_settings
from app.privacy.redactor import count_sensitive_hits
from app.scenarios import case_labeler

# 시나리오 딕트에 반드시 있어야 하는 키
_REQUIRED_KEYS = (
    "title", "category", "risk_family", "scenario_summary",
    "red_flags", "safe_counters", "difficulty",
)

# 위험군별 상대(페르소나) 역할 힌트
_FAMILY_ROLE: dict[str, str] = {
    "off_platform_link": "seller",
    "fake_safe_payment": "seller",
    "delivery_payment_risk": "seller",
    "personal_contact_grooming": "stranger",
    "voice_call_pressure": "stranger",
    "romance_boundary_pressure": "stranger",
    "job_offer_scam": "recruiter",
    "investment_pressure": "stranger",
    "account_takeover": "stranger",
    "refund_conflict": "buyer",
}

# ------------------------------------------------------------
#  위험군별 시나리오 템플릿 (전부 픽션·방어)
#  {title, summary, red_flags, safe_counters, difficulty}
# ------------------------------------------------------------
_TEMPLATES: dict[str, dict] = {
    "off_platform_link": {
        "title": "앱 밖 링크로 결제를 유도하는 상대",
        "summary": (
            "상대가 수수료·속도를 핑계로 앱 밖 외부 링크에서 결제하자고 유도하는 상황이에요. "
            "링크 밖으로 나가면 플랫폼 보호를 받지 못하게 됩니다."
        ),
        "red_flags": [
            "앱 밖 외부 링크에서 결제하자고 유도한다",
            "'수수료 아깝다/더 빠르다'로 정식 절차를 건너뛰라 한다",
            "대화를 앱 밖으로 옮기려 한다",
        ],
        "safe_counters": [
            "외부 링크는 누르지 않고 앱 내 공식 결제만 쓴다",
            "'앱 안에서만 진행하겠다'고 정중히 단호하게 말한다",
            "이상하면 멈추고 신고 버튼을 확인한다",
        ],
        "difficulty": "easy",
    },
    "fake_safe_payment": {
        "title": "가짜 안전결제 페이지 유도",
        "summary": (
            "상대가 '안전결제로 하자'며 정식 플랫폼이 아닌 유사한 외부 안전결제 페이지로 "
            "유도하는 상황이에요. 정식처럼 보여도 플랫폼 밖이라 보호를 못 받습니다."
        ),
        "red_flags": [
            "플랫폼이 아닌 외부 '안전결제' 링크를 보낸다",
            "정식 화면과 비슷하게 꾸며 신뢰를 유도한다",
            "링크에서 추가 정보/결제 입력을 요구한다",
        ],
        "safe_counters": [
            "안전결제는 앱 내 공식 기능으로만 확인한다",
            "외부 링크의 결제/정보 입력 요구는 거절한다",
            "화면·절차가 조금이라도 다르면 진행을 멈춘다",
        ],
        "difficulty": "medium",
    },
    "delivery_payment_risk": {
        "title": "실물 확인 전 선입금을 재촉하는 택배거래",
        "summary": (
            "택배거래에서 상대가 실물 확인 전 선입금을 재촉하는 상황이에요. "
            "확인 절차 없이 먼저 돈을 보내면 회수가 어렵습니다."
        ),
        "red_flags": [
            "실물/구성품 확인 전에 선입금을 요구한다",
            "'지금 안 넣으면 다른 사람에게 넘긴다'로 재촉한다",
            "안전결제 대신 계좌 이체를 고집한다",
        ],
        "safe_counters": [
            "확인 전 입금은 금액이 작아도 거절한다",
            "실물 사진·구성품·상태를 먼저 요청한다",
            "플랫폼 안전결제 절차만 사용한다",
        ],
        "difficulty": "medium",
    },
    "personal_contact_grooming": {
        "title": "앱 밖 개인 연락으로 옮기자는 상대",
        "summary": (
            "상대가 '여기 불편하다'며 개인 메신저·전화로 연락을 옮기자고 하는 상황이에요. "
            "대화가 앱 밖으로 나가면 기록이 사라지고 보호도 약해집니다."
        ),
        "red_flags": [
            "개인 메신저·전화로 연락을 옮기자고 한다",
            "친구 추가/오픈채팅 등 사적 채널을 권한다",
            "'여기서 말고'라며 플랫폼 대화를 피한다",
        ],
        "safe_counters": [
            "'거래 대화는 앱 안에서만 하겠다'고 선을 긋는다",
            "정중하지만 단호하게 개인 연락 유도를 거절한다",
            "기록이 남는 플랫폼 대화를 유지한다",
        ],
        "difficulty": "easy",
    },
    "voice_call_pressure": {
        "title": "전화 본인확인·인증을 압박하는 상대",
        "summary": (
            "상대가 '본인확인이 필요하다'며 전화 통화나 외부 인증을 재촉하는 상황이에요. "
            "통화로 넘어가 인증번호·정보를 부르게 만드는 압박 패턴입니다."
        ),
        "red_flags": [
            "전화 통화·외부 인증을 급하게 요구한다",
            "인증번호/개인정보를 불러달라 한다",
            "'지금 안 하면 큰일 난다'로 겁을 준다",
        ],
        "safe_counters": [
            "전화·외부 인증 요구는 공식 채널로만 확인한다",
            "인증번호·개인정보는 누구에게도 불러주지 않는다",
            "재촉당할수록 한 박자 멈추고 확인한다",
        ],
        "difficulty": "hard",
    },
    "romance_boundary_pressure": {
        "title": "호감을 앞세워 판단을 흐리는 접근",
        "summary": (
            "상대가 짧은 대화에도 지나친 호감·친밀감으로 신뢰를 앞세우는 상황이에요. "
            "감정적 신뢰가 거래·금전 판단을 흐리게 만드는 전형적 압박입니다."
        ),
        "red_flags": [
            "만난 지 얼마 안 됐는데 과한 애정/신뢰를 표현한다",
            "감정을 근거로 금전·거래 부탁을 슬쩍 끼운다",
            "'우리 사이에 왜 못 믿냐'로 경계를 무너뜨린다",
        ],
        "safe_counters": [
            "감정과 거래 판단을 분리한다",
            "금전이 얽히면 한 박자 멈추고 사실만 확인한다",
            "친밀감을 이유로 절차를 건너뛰지 않는다",
        ],
        "difficulty": "medium",
    },
    "job_offer_scam": {
        "title": "먼저 입금을 요구하는 부업/알바 제안",
        "summary": (
            "상대가 고수익 부업·알바를 미끼로 선수수료·가입비를 먼저 입금하라 하는 상황이에요. "
            "정식 채용은 지원자에게 먼저 돈을 요구하지 않습니다."
        ),
        "red_flags": [
            "일 시작 전에 수수료·가입비를 먼저 입금하라 한다",
            "'쉽고 큰 수익'을 장담한다",
            "검증 없이 외부 채널/링크로 유도한다",
        ],
        "safe_counters": [
            "먼저 입금 요구는 거절하고 정식 채용 절차만 신뢰한다",
            "'쉬운 고수익'일수록 왜 그런지 먼저 의심한다",
            "외부 링크·개인 연락 유도는 따르지 않는다",
        ],
        "difficulty": "medium",
    },
    "investment_pressure": {
        "title": "고수익을 앞세운 투자 재촉",
        "summary": (
            "상대가 '확정 수익', '지금만 기회'라며 빠른 투자 결정을 재촉하는 상황이에요. "
            "지나치게 좋은 조건과 시간 압박이 겹치는 전형적 유인입니다."
        ),
        "red_flags": [
            "'원금 보장/확정 수익'을 장담한다",
            "'오늘만/지금만'으로 결정을 재촉한다",
            "검증 없이 외부 채널/링크로 유도한다",
        ],
        "safe_counters": [
            "'너무 좋은 조건'일수록 왜 그런지 먼저 의심한다",
            "재촉에는 결정을 미루고 독립적으로 확인한다",
            "확정 수익 약속은 신뢰의 근거가 아니라 위험 신호로 본다",
        ],
        "difficulty": "medium",
    },
    "account_takeover": {
        "title": "계정·인증정보를 노리는 접근",
        "summary": (
            "상대가 그럴듯한 핑계로 계정·비밀번호·인증정보를 요구하는 상황이에요. "
            "정상적인 거래·문의에서는 상대에게 인증정보를 넘길 일이 없습니다."
        ),
        "red_flags": [
            "계정/비밀번호/인증정보를 요구한다",
            "'확인용'이라며 인증번호를 불러달라 한다",
            "링크에 로그인 정보를 입력하게 만든다",
        ],
        "safe_counters": [
            "인증정보·비밀번호는 누구에게도 알려주지 않는다",
            "인증번호를 요구하면 즉시 거래를 멈춘다",
            "로그인은 공식 앱/화면에서만 한다",
        ],
        "difficulty": "hard",
    },
    "refund_conflict": {
        "title": "근거 없이 환불을 압박하는 상대",
        "summary": (
            "판매자 입장에서, 상대가 명확한 하자 근거 없이 협박성 어조로 환불을 요구하는 상황이에요. "
            "감정에 휘말리지 않고 고지·기록 중심으로 대응해야 합니다."
        ),
        "red_flags": [
            "구체적 하자 근거 없이 환불부터 요구한다",
            "악평·신고를 무기로 압박한다",
            "고지된 상태를 무시하고 책임을 전가한다",
        ],
        "safe_counters": [
            "감정 대신 사전 고지·거래 기록을 근거로 답한다",
            "정당한 하자 주장인지 사실 기준으로 구분한다",
            "침착하게 기준선을 유지하며 대화를 기록으로 남긴다",
        ],
        "difficulty": "hard",
    },
}

# 폴백 템플릿 (알 수 없는 위험군)
_DEFAULT_TEMPLATE = {
    "title": "정식 절차를 건너뛰라는 압박 상황",
    "summary": (
        "상대가 그럴듯한 핑계로 정식 절차를 건너뛰라고 유도하는 상황이에요. "
        "절차를 생략할수록 보호가 약해진다는 점을 기억하세요."
    ),
    "red_flags": [
        "정식 절차를 건너뛰라고 유도한다",
        "재촉·핑계로 판단할 시간을 주지 않는다",
        "확인 요청을 회피한다",
    ],
    "safe_counters": [
        "정식 절차만 따르고, 이상하면 멈추고 확인한다",
        "재촉당할수록 한 박자 멈춘다",
        "확인이 거절되면 거래를 진행하지 않는다",
    ],
    "difficulty": "medium",
}


def _build_persona_seed(family: str, labels: dict) -> dict:
    """상대(페르소나) 시드 — 방어 관찰 포인트용. 실제 인물/개인정보 없음."""
    return {
        "counterpart_role": _FAMILY_ROLE.get(family, "stranger"),
        "risk_family": family,
        "pressure_style": labels.get("pressure_type", "none"),
        "typical_request": labels.get("requested_action", ""),
        # '약점 프로필' = 이 상대가 의존하는 압박 신호 (플레이어가 관찰·방어할 지점)
        "weakness_profile": (
            f"이 상대는 '{labels.get('requested_action', '정식 절차 우회')}'로 판단을 흐리려 한다. "
            f"핵심 방어: {labels.get('safe_response', '정식 절차만 따른다')}"
        ),
        "opening_style": "친절하지만 정식 절차를 은근히 건너뛰게 만드는 어조",
    }


def _template_scenario(case: dict, labels_result: dict) -> dict:
    """규칙 기반 템플릿으로 픽션화된 시나리오 딕트를 만든다 (사례 본문 미복제)."""
    labels = labels_result.get("labels", {})
    family = labels_result.get("risk_family") or "off_platform_link"
    category = labels_result.get("category") or "used_marketplace"
    tpl = _TEMPLATES.get(family, _DEFAULT_TEMPLATE)

    return {
        "title": tpl["title"],
        "category": category,
        "risk_family": family,
        "scenario_summary": tpl["summary"],
        "red_flags": list(tpl["red_flags"]),
        "safe_counters": list(tpl["safe_counters"]),
        "difficulty": tpl.get("difficulty", "medium"),
        "persona_seed": _build_persona_seed(family, labels),
        "labels": {
            "scam_type": labels.get("scam_type", family),
            "pressure_type": labels.get("pressure_type", "none"),
            "training_module": labels.get("training_module", ""),
        },
    }


def validate_generated_scenario(scenario: dict, case: dict) -> tuple[bool, list[str]]:
    """생성 시나리오 안전 검증. (통과여부, 문제목록) 반환.

    규칙:
      - 필수 키 존재
      - category / risk_family 비어 있지 않음
      - red_flags / safe_counters 는 비어 있지 않은 리스트
      - 계좌/URL/전화처럼 보이는 민감정보 0건 (합쳐서 검사)
      - 사례 본문과 동일하지 않음 (원문 복제 금지)
    """
    issues: list[str] = []
    if not isinstance(scenario, dict):
        return False, ["시나리오가 딕트 형태가 아니에요."]

    for key in _REQUIRED_KEYS:
        if key not in scenario:
            issues.append(f"필수 키 누락: {key}")

    if not str(scenario.get("category") or "").strip():
        issues.append("category 가 비어 있어요.")
    if not str(scenario.get("risk_family") or "").strip():
        issues.append("risk_family 가 비어 있어요.")

    red_flags = scenario.get("red_flags")
    safe_counters = scenario.get("safe_counters")
    if not isinstance(red_flags, list) or len(red_flags) == 0:
        issues.append("red_flags 는 비어 있지 않은 리스트여야 해요.")
    if not isinstance(safe_counters, list) or len(safe_counters) == 0:
        issues.append("safe_counters 는 비어 있지 않은 리스트여야 해요.")

    # 민감정보(계좌/URL/전화 등) 0건이어야 한다.
    parts: list[str] = [
        str(scenario.get("title") or ""),
        str(scenario.get("scenario_summary") or ""),
    ]
    if isinstance(red_flags, list):
        parts.extend(str(x) for x in red_flags)
    if isinstance(safe_counters, list):
        parts.extend(str(x) for x in safe_counters)
    joined = "\n".join(parts)
    try:
        if count_sensitive_hits(joined) > 0:
            issues.append("민감정보(계좌/URL/전화처럼 보이는 값)가 포함돼 있어요.")
    except Exception:
        # 검사기 자체가 실패하면 보수적으로 문제로 본다.
        issues.append("민감정보 검사에 실패했어요.")

    # 사례 본문 복제 금지
    case_body = str((case or {}).get("redacted_body") or "").strip()
    summary = str(scenario.get("scenario_summary") or "").strip()
    if case_body and summary and (summary == case_body or case_body in summary):
        issues.append("사례 본문을 그대로 복제했어요. 일반화가 필요해요.")

    return (len(issues) == 0), issues


def _llm_draft_scenario(provider: str, case: dict, labels_result: dict) -> dict | None:
    """LLM 초안 생성 훅 (pluggable). 현재는 안전 폴백을 위해 None 을 돌려준다.

    구조:
      - provider 가 local_claude/openai 일 때만 호출된다.
      - 실제 provider 모듈을 붙일 때 여기서 초안 dict 를 만들어 반환하면,
        호출부가 validate_generated_scenario 로 검증한 뒤 채택/폴백을 결정한다.
      - 어떤 이유로든(미구현/타임아웃/예외) None 을 돌려주면 template 로 폴백한다.
    """
    try:
        # 향후 연동 지점: app.ai 의 provider 어댑터로 초안 JSON 생성 → dict 반환.
        # 지금은 오프라인 안전을 위해 초안을 만들지 않는다 (항상 template 폴백).
        return None
    except Exception:
        return None


def generate_scenario_from_case(conn: sqlite3.Connection, case: dict) -> dict:
    """커뮤니티 사례(비식별) → 방어 시나리오. 기본 provider=template.

    반환:
      {"scenario": <dict>, "provider_used": str, "requires_review": bool}
    """
    settings = get_settings()
    provider = settings.case_scenario_provider_effective
    requires_review = bool(settings.case_scenario_requires_review)

    # a) 규칙 기반 라벨 추출
    try:
        labels_result = case_labeler.extract_case_labels(case or {})
    except Exception:
        labels_result = {
            "labels": {}, "confidence": {},
            "risk_family": "off_platform_link", "category": "used_marketplace",
        }

    # b) 템플릿 시나리오 (항상 안전한 기본값)
    template_scenario = _template_scenario(case or {}, labels_result)
    provider_used = "template"
    scenario = template_scenario

    # c) provider 가 LLM 이면 초안 시도 → 반드시 검증 통과해야 채택
    if provider in ("local_claude", "openai"):
        try:
            draft = _llm_draft_scenario(provider, case or {}, labels_result)
            if isinstance(draft, dict):
                ok, _issues = validate_generated_scenario(draft, case or {})
                if ok:
                    scenario = draft
                    provider_used = provider
                # 검증 실패면 template 유지 (이미 scenario=template)
        except Exception:
            # LLM 경로 실패는 언제나 template 로 폴백
            scenario = template_scenario
            provider_used = "template"

    return {
        "scenario": scenario,
        "provider_used": provider_used,
        "requires_review": requires_review,
    }
