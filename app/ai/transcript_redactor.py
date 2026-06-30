"""
대화 기록 비식별화 (transcript redaction).

적응형 엔진은 기본적으로 '구조화된 메타데이터 + 짧은 요약(digest)'만 저장한다.
원문 대화는 STORE_REDACTED_TRANSCRIPTS=true 일 때만, 그것도 '비식별화 후'에만 저장한다.

여기서 지우는 것:
  - 전화번호, 이메일, URL
  - 계좌/카드 같은 긴 숫자열
  - 분명한 주소
  - 주민등록번호류 패턴
  - API 키 / 액세스 토큰
  - 과도하게 긴 붙여넣기 텍스트

대체 토큰: [PHONE] [EMAIL] [URL] [ACCOUNT_OR_LONG_NUMBER] [ADDRESS] [SECRET]

원칙: 개인정보/민감정보는 '저장 전에' 제거한다. 정답 노출 방지(role/tactic)는 라우터에서
이미 막으므로, 여기 목적은 프라이버시 보호다.
"""
from __future__ import annotations

import re

# 순서가 중요하다(겹치는 패턴은 더 구체적인 것을 먼저). 토큰화 후 재매칭을 피하려고
# 토큰 자체에는 영문 대문자/대괄호만 쓴다.
_SECRET = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}"
    r"|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})\b"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# URL: 정상 http(s)/www + 사기 시뮬에서 쓰는 난독화 도메인(example[.]com, cj-track[.]net, paysite[.]xyz) 도 잡는다.
# 두 번째 분기는 TLD 화이트리스트 없이 임의 TLD(.shop/.vip/.xyz/.ru/...)와 '[.]' 난독화를 모두 잡는다.
# (incidental 토큰 over-redaction 은 프라이버시 보호 측면에서 허용된다.)
_URL = re.compile(
    r"\b(?:https?://|www\.)\S+"
    r"|\b[\w\-]+(?:\s*\[\.\]\s*|\.)(?:[\w\-]+(?:\s*\[\.\]\s*|\.))*[a-z]{2,}\b(?:/\S*)?",
    re.IGNORECASE,
)
# 주민등록번호류: 6자리-7자리
_RRN = re.compile(r"\b\d{6}\s*[-–]\s*\d{7}\b")
# 전화번호: 010-1234-5678 / 02-123-4567 / +82 10 ... 등
_PHONE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?(?:0\d{1,2}|01\d)[\s\-]?\d{3,4}[\s\-]?\d{4}\b"
)
# 계좌/카드 같은 긴 숫자열(구분자 포함 9자리 이상)
_LONG_NUMBER = re.compile(r"\b\d[\d\s\-]{7,}\d\b")
# 분명한 주소: '...시/도 ...구/군 ... 동/로/길 [번지/숫자]' 가 한 덩어리로 보일 때
_ADDRESS = re.compile(
    r"[가-힣]+(?:특별시|광역시|시|도)\s?[가-힣]+(?:시|군|구)\s?[가-힣0-9]+(?:읍|면|동|로|길)"
    r"(?:\s?\d{1,4}(?:-\d{1,4})?(?:번지|번길|호)?)?"
)

_MAX_MESSAGE_CHARS = 600  # 과도하게 긴 붙여넣기 방어


def redact_text(text: str) -> str:
    """한 문자열에서 민감정보를 토큰으로 치환한다."""
    s = str(text or "")
    s = _SECRET.sub("[SECRET]", s)
    s = _EMAIL.sub("[EMAIL]", s)
    s = _URL.sub("[URL]", s)
    s = _RRN.sub("[SECRET]", s)
    s = _ADDRESS.sub("[ADDRESS]", s)
    s = _PHONE.sub("[PHONE]", s)
    s = _LONG_NUMBER.sub("[ACCOUNT_OR_LONG_NUMBER]", s)
    s = s.strip()
    if len(s) > _MAX_MESSAGE_CHARS:
        s = s[:_MAX_MESSAGE_CHARS].rstrip() + "…"
    return s


def redact_transcript(transcript: list[dict]) -> list[dict]:
    """대화 기록 전체를 비식별화한다. 정답(tactic) 같은 내부 라벨은 담지 않는다.

    저장용 최소 필드만 남긴다: speaker / content(비식별) / flagged_by_player.
    """
    out: list[dict] = []
    for m in transcript or []:
        speaker = "npc" if m.get("speaker") == "npc" else "player"
        out.append({
            "speaker": speaker,
            "content": redact_text(m.get("content", "")),
            "flagged_by_player": bool(m.get("flagged_by_player")),
        })
    return out


def make_transcript_digest(transcript: list[dict], max_chars: int = 500) -> str:
    """원문이 아닌 '안전한 짧은 요약' 한 줄.

    누가 몇 마디 했고, 위험표시(🚩)를 몇 번 눌렀는지 같은 집계만 담는다.
    개별 발화 원문은 담지 않는다(담더라도 비식별 후 아주 짧게).
    """
    msgs = transcript or []
    npc_turns = sum(1 for m in msgs if m.get("speaker") == "npc")
    player_turns = sum(1 for m in msgs if m.get("speaker") == "player")
    flagged = sum(1 for m in msgs if m.get("speaker") == "npc" and m.get("flagged_by_player"))
    digest = (
        f"총 {len(msgs)}메시지(상대 {npc_turns} · 나 {player_turns}), "
        f"의심표시 {flagged}건."
    )
    if len(digest) > max_chars:
        digest = digest[:max_chars].rstrip() + "…"
    return digest
