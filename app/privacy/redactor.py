"""
사용자 제출 텍스트 비식별화 (community case / comment 저장 전 필수 단계).

원칙:
  - 원문(raw)은 기본적으로 저장하지 않는다. 저장 전에 여기서 민감정보를 토큰으로 가린다.
  - 이미 있는 app/ai/transcript_redactor 의 패턴을 재사용하되, 사용자 제출 맥락에 맞게
    카카오/텔레그램/라인/오픈채팅 같은 '사적 연락 채널'을 [PRIVATE_CONTACT] 로 추가로 가린다.
  - 무엇을 가렸는지(redacted_types)와 위험 신호 힌트(risk_flags)를 메타로 돌려준다.

대체 토큰:
  [PHONE] [EMAIL] [URL] [ACCOUNT] [ID_NUMBER] [ADDRESS] [SECRET] [PRIVATE_CONTACT]
"""
from __future__ import annotations

import re

# 순서가 중요하다: 더 구체적인 패턴을 먼저 치환한다.
# 토큰 자체에는 영문 대문자/대괄호만 써서 재매칭을 피한다.

_SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}"
    r"|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})\b"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# 카카오/텔레그램/라인/오픈채팅 같은 사적 연락 채널 유도.
# open.kakao.com / t.me / line.me 링크 + 'kakao id: ...', '오픈채팅', '텔레 @handle' 등.
_PRIVATE_CONTACT = re.compile(
    r"\b(?:open\.kakao\.com|t\.me|line\.me)/\S+"
    r"|\b(?:오픈\s?채팅|오픈카톡)\S*"
    r"|\b(?:카카오톡?|카톡|텔레그램|텔레|라인|line|kakao|telegram)\s*"
    r"(?:아이디|id|친구|추가|오픈)?\s*[:：]?\s*@?[A-Za-z0-9_.\-]{2,}",
    re.IGNORECASE,
)

# URL: 정상 http(s)/www + 난독화 도메인(example[.]com) 모두.
_URL = re.compile(
    r"\b(?:https?://|www\.)\S+"
    r"|\b[\w\-]+(?:\s*\[\.\]\s*|\.)(?:[\w\-]+(?:\s*\[\.\]\s*|\.))*[a-z]{2,}\b(?:/\S*)?",
    re.IGNORECASE,
)

# 주민등록번호류: 6자리-7자리
_ID_NUMBER = re.compile(r"\b\d{6}\s*[-–]\s*\d{7}\b")

# 전화번호: 010-1234-5678 / 02-123-4567 / +82 10 ... 등
_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?(?:0\d{1,2}|01\d)[\s\-]?\d{3,4}[\s\-]?\d{4}\b"
)

# 계좌/카드 같은 긴 숫자열(구분자 포함 9자리 이상)
_ACCOUNT = re.compile(r"\b\d[\d\s\-]{7,}\d\b")

# 분명한 주소: '...시/도 ...구/군 ... 동/로/길 [번지/숫자]'
_ADDRESS = re.compile(
    r"[가-힣]+(?:특별시|광역시|시|도)\s?[가-힣]+(?:시|군|구)\s?[가-힣0-9]+(?:읍|면|동|로|길)"
    r"(?:\s?\d{1,4}(?:-\d{1,4})?(?:번지|번길|호)?)?"
)

_MAX_CHARS = 2000  # 과도하게 긴 붙여넣기 방어 (사례 본문은 커밋 시 별도 상한도 있음)

# 어떤 토큰이 어떤 위험 신호로 연결되는지 (라벨링/시나리오 힌트)
_RISK_FLAG_BY_TYPE = {
    "PRIVATE_CONTACT": "private_contact",
    "URL": "external_link",
    "ACCOUNT": "account_transfer",
    "PHONE": "off_platform_contact",
    "ID_NUMBER": "identity_exposure",
    "SECRET": "credential_exposure",
}


def redact_sensitive_text(text: str) -> tuple[str, dict]:
    """한 문자열의 민감정보를 토큰으로 치환하고, (치환문자열, 메타) 를 돌려준다.

    메타:
      {
        "redacted_types": ["PHONE", "URL", ...],   # 실제로 가린 유형(발견된 것만)
        "risk_flags": ["private_contact", ...],     # 위험 신호 힌트(중복 제거)
        "truncated": bool,                          # 길이 상한으로 잘렸는가
      }
    """
    s = str(text or "")
    found: list[str] = []

    def _sub(pattern: re.Pattern, token_type: str, replacement: str, value: str) -> str:
        nonlocal found
        if pattern.search(value):
            found.append(token_type)
            return pattern.sub(replacement, value)
        return value

    # 구체적 → 일반 순서 (URL 앞에 PRIVATE_CONTACT/EMAIL/SECRET 를 먼저 처리)
    s = _sub(_SECRET, "SECRET", "[SECRET]", s)
    s = _sub(_EMAIL, "EMAIL", "[EMAIL]", s)
    s = _sub(_PRIVATE_CONTACT, "PRIVATE_CONTACT", "[PRIVATE_CONTACT]", s)
    s = _sub(_URL, "URL", "[URL]", s)
    s = _sub(_ID_NUMBER, "ID_NUMBER", "[ID_NUMBER]", s)
    s = _sub(_ADDRESS, "ADDRESS", "[ADDRESS]", s)
    s = _sub(_PHONE, "PHONE", "[PHONE]", s)
    s = _sub(_ACCOUNT, "ACCOUNT", "[ACCOUNT]", s)

    s = s.strip()
    truncated = False
    if len(s) > _MAX_CHARS:
        s = s[:_MAX_CHARS].rstrip() + "…"
        truncated = True

    # 순서 보존 + 중복 제거
    redacted_types = list(dict.fromkeys(found))
    risk_flags = list(dict.fromkeys(
        _RISK_FLAG_BY_TYPE[t] for t in redacted_types if t in _RISK_FLAG_BY_TYPE
    ))
    return s, {
        "redacted_types": redacted_types,
        "risk_flags": risk_flags,
        "truncated": truncated,
    }


def count_sensitive_hits(text: str) -> int:
    """원문에서 발견된 민감정보 '건수' 대략 집계 (moderation 의 과다 개인정보 판단용)."""
    s = str(text or "")
    total = 0
    for pattern in (_SECRET, _EMAIL, _PRIVATE_CONTACT, _URL, _ID_NUMBER,
                    _PHONE, _ACCOUNT, _ADDRESS):
        total += len(pattern.findall(s))
    return total
