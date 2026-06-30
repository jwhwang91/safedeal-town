"""
안전한 페르소나/매물 변주 빌더.

선택된 '훈련 패턴'을 바탕으로, NPC 가 매 세션 '다르게 느껴지도록' 표면(말투/페이싱/오프닝
뉘앙스)만 바꾼다. 정답(role/tactics/mock 진실)은 절대 바꾸지 않는다.

제공자:
  - template       : 결정/안전한 로컬 생성 (기본값)
  - local_claude   : 로컬 Claude CLI (있으면). 실패 시 template 폴백
  - openai         : OpenAI 호환 (있으면). 실패 시 template 폴백

모든 제공자 출력은 검증한다. 아래가 하나라도 있으면 거부하고 template 로 폴백한다:
  - 실제 URL/이메일/전화번호/계좌 같은 긴 숫자
  - "bypass detection", "steal credentials", "fake payment page" 류의 실행적 사기 문구
이로써 이 모듈은 절대 실행적 사기 절차/링크/자격증명 수집을 만들지 않는다.
"""
from __future__ import annotations

from app.ai import transcript_redactor as redactor
from app.ai.provider import active_provider, call_llm_json

# 난이도 가감 → 페이싱/말투 프리셋 (LLM NPC 를 '연출'하는 안전한 지시문)
_TONE_PRESETS = {
    "harder": {
        "tone": "차분하고 미묘함",
        "pacing_notes": "처음엔 평범한 대화로 신뢰를 쌓고, 위화감은 아주 천천히 흘린다.",
        "difficulty_notes": "잘 대응하는 상대 — 신호를 덜 노골적으로, 더 자연스럽게.",
        "speech_suffix": " 서두르지 않고 또박또박, 상대를 안심시키듯 말한다.",
    },
    "easier": {
        "tone": "분명하고 직설적",
        "pacing_notes": "위화감 신호를 비교적 일찍, 알아보기 쉽게 드러낸다.",
        "difficulty_notes": "연습 단계 — 신호를 조금 더 또렷하게.",
        "speech_suffix": " 감정과 의도가 비교적 일찍 드러난다.",
    },
    "same": {
        "tone": "자연스럽고 균형 잡힘",
        "pacing_notes": "대화 흐름에 맞춰 자연스럽게 페이스를 잡는다.",
        "difficulty_notes": "표준 난이도.",
        "speech_suffix": "",
    },
}

# 검증: 실행적 사기/악성 문구 차단 (한/영)
_FORBIDDEN_PHRASES = [
    "bypass detection", "steal credential", "credential theft", "fake payment page",
    "phishing", "keylog", "carding", "account takeover",
    "결제 페이지", "계좌번호", "카드번호", "카드정보 입력", "비밀번호 입력",
    "탐지 우회", "탐지를 우회", "자격증명", "개인정보 입력", "송금받",
]


def _is_safe_text(text: str) -> bool:
    """민감정보/실행적 사기 문구가 없는 안전한 표시 텍스트인지."""
    s = str(text or "")
    # 비식별기로 걸러서 내용이 바뀌면 = 민감정보(전화/이메일/URL/계좌)를 포함했다는 뜻 → 거부
    if redactor.redact_text(s) != s.strip():
        return False
    low = s.lower()
    return not any(bad in low or bad in s for bad in _FORBIDDEN_PHRASES)


def _validate_variant(variant: dict) -> bool:
    if not isinstance(variant, dict):
        return False
    for key in ("personality", "speech_style", "backstory", "opening_line",
                "tone", "pacing_notes", "difficulty_notes", "display_name"):
        val = variant.get(key)
        if val and not _is_safe_text(str(val)):
            return False
    for label in variant.get("pattern_labels", []) or []:
        if not _is_safe_text(str(label)):
            return False
    return True


# ============================================================
#  template 제공자 (기본값, 항상 안전)
# ============================================================
def _template_variant(base_persona: dict, selected_patterns: list[dict],
                      game_role: str, difficulty_adjustment: str) -> dict:
    preset = _TONE_PRESETS.get(difficulty_adjustment, _TONE_PRESETS["same"])
    base_persona = base_persona or {}
    labels = [p.get("label") for p in (selected_patterns or []) if p.get("label")]

    personality = str(base_persona.get("personality", "평범한 성격"))
    speech = str(base_persona.get("speech_style", "평범한 채팅체")) + preset["speech_suffix"]

    return {
        "display_name": None,  # template 은 공개 이름을 바꾸지 않는다 (혼선 방지)
        "personality": personality,
        "speech_style": speech.strip(),
        "backstory": str(base_persona.get("backstory", "")),
        "opening_line": str(base_persona.get("opening_line", "")),  # 매물 맥락 보존
        "scenario_type": (selected_patterns[0]["pattern_family"]
                          if selected_patterns else "balanced"),
        "pattern_labels": labels[:4],
        "tone": preset["tone"],
        "pacing_notes": preset["pacing_notes"],
        "difficulty_notes": preset["difficulty_notes"],
        "provider": "template",
    }


# ============================================================
#  LLM 제공자 (선택) — 안전하게 검증, 실패 시 template
# ============================================================
_VARIANT_SYSTEM = (
    "너는 방어형 중고거래 훈련 시뮬레이터의 'NPC 연출 보조'다. "
    "주어진 페르소나의 '표면 연출'(말투/배경 한 줄/페이싱 뉘앙스)만 안전하게 변주한다.\n"
    "절대 금지: 실제 URL·이메일·전화번호·계좌/카드 번호 생성, 가짜 결제 페이지/링크, "
    "자격증명 수집, 탐지 우회, 협박/괴롭힘, 실행적 사기 절차, 법적 단정.\n"
    "출력은 아래 JSON 하나만: "
    '{"personality": "...", "speech_style": "...", "backstory": "...", '
    '"opening_line": "...", "tone": "...", "pacing_notes": "..."}'
)


def _llm_variant(base_persona: dict, listing: dict | None, selected_patterns: list[dict],
                 game_role: str, difficulty_adjustment: str) -> dict | None:
    if active_provider() == "mock":
        return None  # 제공자 없음 → template 폴백
    labels = ", ".join(p.get("label", "") for p in (selected_patterns or []))
    user_payload = (
        f"역할: {game_role} 모드의 상대 NPC\n"
        f"기존 페르소나: 성격={base_persona.get('personality','')} / "
        f"말투={base_persona.get('speech_style','')} / 배경={base_persona.get('backstory','')}\n"
        f"오프닝(맥락 보존, 크게 바꾸지 말 것): {base_persona.get('opening_line','')}\n"
        f"난이도 가감: {difficulty_adjustment}\n"
        f"이번에 자연스럽게 다룰 수 있는 위험 신호(라벨만, 실행 절차 금지): {labels}\n"
        "위 페르소나를 같은 인물로 유지하되 말투/배경/페이싱만 살짝 다르게 변주해라."
    )
    try:
        result = call_llm_json(_VARIANT_SYSTEM, [{"role": "user", "content": user_payload}],
                               temperature=0.7)
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    variant = {
        "display_name": None,
        "personality": redactor.redact_text(str(result.get("personality", ""))) or
        base_persona.get("personality", ""),
        "speech_style": redactor.redact_text(str(result.get("speech_style", ""))) or
        base_persona.get("speech_style", ""),
        "backstory": redactor.redact_text(str(result.get("backstory", ""))) or
        base_persona.get("backstory", ""),
        # 오프닝은 매물 맥락 보존을 위해 기존 것을 우선 유지
        "opening_line": base_persona.get("opening_line", ""),
        "scenario_type": (selected_patterns[0]["pattern_family"]
                          if selected_patterns else "balanced"),
        "pattern_labels": [p.get("label") for p in (selected_patterns or []) if p.get("label")][:4],
        "tone": redactor.redact_text(str(result.get("tone", ""))) or "자연스러움",
        "pacing_notes": redactor.redact_text(str(result.get("pacing_notes", ""))),
        "difficulty_notes": _TONE_PRESETS.get(difficulty_adjustment,
                                              _TONE_PRESETS["same"])["difficulty_notes"],
        "provider": active_provider(),
    }
    return variant if _validate_variant(variant) else None


# ============================================================
#  공개 API
# ============================================================
def build_persona_variant(base_persona: dict, listing: dict | None,
                          selected_patterns: list[dict], game_role: str,
                          difficulty_adjustment: str, provider: str = "template") -> dict:
    """안전한 페르소나 변주를 만든다. 어떤 경우에도 검증된 안전 dict 를 돌려준다.

    실패/검증 거부 시 template 로 폴백하므로 게임은 절대 멈추지 않는다.
    """
    if provider in ("local_claude", "openai"):
        variant = _llm_variant(base_persona, listing, selected_patterns,
                               game_role, difficulty_adjustment)
        if variant and _validate_variant(variant):
            return variant
    # template (기본/폴백)
    variant = _template_variant(base_persona, selected_patterns,
                                game_role, difficulty_adjustment)
    return variant if _validate_variant(variant) else _safe_minimal(base_persona)


def _safe_minimal(base_persona: dict) -> dict:
    """최후의 안전망 — 원래 페르소나를 유지하되 텍스트는 비식별화해 '항상 검증 통과'를 보장한다.

    (이 분기는 template 변주가 검증에 실패했을 때만 도달하므로, base 필드 자체가 민감정보를
    품고 있을 수 있다. redact 후 반환해 build_persona_variant 의 '검증된 안전 dict' 계약을 지킨다.)
    """
    base_persona = base_persona or {}
    return {
        "display_name": None,
        "personality": redactor.redact_text(str(base_persona.get("personality", "평범한 성격"))) or "평범한 성격",
        "speech_style": redactor.redact_text(str(base_persona.get("speech_style", "평범한 채팅체"))) or "평범한 채팅체",
        "backstory": redactor.redact_text(str(base_persona.get("backstory", ""))),
        "opening_line": redactor.redact_text(str(base_persona.get("opening_line", ""))),
        "scenario_type": "balanced",
        "pattern_labels": [],
        "tone": "자연스러움",
        "pacing_notes": "",
        "difficulty_notes": "",
        "provider": "template",
    }


def apply_variant_to_npc(npc: dict, variant: dict) -> dict:
    """변주의 '표시 필드'만 NPC 에 입힌다. role/tactics/mock_lines/notes 등 정답은 보존.

    이 함수가 만든 새 NPC dict 가 이번 세션의 system 프롬프트/오프닝에 쓰인다.
    """
    if not variant:
        return npc
    out = dict(npc)
    persona = dict(out.get("persona") or {})
    # 표시/연출용 필드만 덮어쓴다 (honest_note/buyer_note 등 진실/가이드는 건드리지 않음)
    for key in ("personality", "speech_style", "backstory", "opening_line"):
        val = variant.get(key)
        if val and _is_safe_text(str(val)):
            persona[key] = str(val)
    out["persona"] = persona
    if variant.get("display_name") and _is_safe_text(str(variant["display_name"])):
        out["name"] = str(variant["display_name"])
    return out
