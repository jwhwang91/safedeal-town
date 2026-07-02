"""
페르소나 '정체성' 재료: 얼굴에 맞춘 겉모습·성별 일치 이름·MBTI 말투.

핵심 원칙 — 얼굴(초상)이 '진실'이다:
  1) 스폰마다 초상을 '먼저' 고른다(app.portraits.resolve_portrait_entry, 스폰 id 시드).
  2) 그 얼굴의 중립 외형 속성(나이대/옷차림/액세서리)에서 '겉모습 설명'을 만든다.
  3) 얼굴의 성별표현에 '맞는' 이름을 고른다.
  → '건우'(남자 이름)인데 여자 얼굴, '후드에 안경 쓴 20대'인데 정장 여성 얼굴 같은
    불일치가 원천적으로 사라진다(설명이 실제 이미지에서 파생되므로).

정답지 보호:
  - 겉모습 설명에 쓰는 속성은 나이/옷차림/액세서리처럼 '역할(정상/사기)과 무관한' 중립
    정보뿐이다. archetype/vibe/family 같은 상관 신호는 공개 설명에 절대 넣지 않는다.
  - MBTI/성별 말투도 role 과 '독립적으로' 정한다 → 말투로도 정답이 새지 않는다.
    (사기꾼도 ENFP·INTJ 무엇이든 될 수 있고, 정상도 마찬가지.)
"""
from __future__ import annotations

import random

# ============================================================
#  성별 일치 이름 풀
# ============================================================
# 얼굴의 성별표현(feminine/masculine)에 '맞는' 이름만 고른다.
# 남녀 혼동이 큰 유니섹스 이름은 neutral 폴백에만 둔다.
_NAMES_MASCULINE = [
    "민수", "도윤", "준호", "현우", "지훈", "성민", "정우", "도경", "예준", "시우",
    "태경", "건우", "준우", "재민", "우진", "지환", "승현", "민재", "성훈", "동혁",
]
_NAMES_FEMININE = [
    "서연", "예린", "수빈", "하은", "보라", "민서", "소율", "채원", "수아", "윤아",
    "나래", "예은", "서윤", "다은", "가은", "혜원", "은지", "지아", "세은", "유나",
]
# 성별을 특정하기 애매할 때만 쓰는 유니섹스 풀.
_NAMES_NEUTRAL = ["유진", "재희", "지안", "한결", "가람", "다온", "서준", "하율"]


def pick_name(gender: str | None, rng: random.Random) -> str:
    """얼굴 성별표현에 맞는 given name 한 개."""
    g = (gender or "").strip().lower()
    if g == "feminine":
        return rng.choice(_NAMES_FEMININE)
    if g == "masculine":
        return rng.choice(_NAMES_MASCULINE)
    return rng.choice(_NAMES_NEUTRAL)


# ============================================================
#  MBTI → 채팅 말투 성향 (16유형, 4축 조합)
# ============================================================
MBTI_TYPES = [
    "ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
    "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ",
]

# 각 축의 '텍스트 채팅에서 드러나는' 짧은 말투 성향 조각.
_AXIS = {
    "E": "말이 많고 리액션이 크며 먼저 말을 건다",
    "I": "말수가 적고 담백하게 필요한 말만 한다",
    "S": "구체적인 사실·상태·구성품 등 실제 정보 위주로 말한다",
    "N": "큰 그림·가능성·비유를 곁들여 말한다",
    "T": "논리와 팩트 중심으로 간결하게, 감정 표현은 적다",
    "F": "공감과 감정 표현이 많고 'ㅎㅎ','ㅠ','!' 나 이모티콘을 자주 쓴다",
    "J": "정돈된 문장으로 계획적으로, 마침표를 또박또박 찍는다",
    "P": "즉흥적이고 자유로운 문장으로 가볍게 흘리듯 말한다",
}


def mbti_style(mbti: str) -> str:
    """MBTI 4글자 → 채팅 말투 성향 한 줄(4개 조각을 쉼표로 연결)."""
    m = (mbti or "").upper()
    letters = [m[i] if i < len(m) else "" for i in range(4)]
    frags = [_AXIS.get(c) for c in letters if c in _AXIS]
    return ", ".join(f for f in frags if f)


def pick_mbti(rng: random.Random) -> tuple[str, str]:
    """role 과 무관한 MBTI 하나 + 그 말투 성향 문장."""
    m = rng.choice(MBTI_TYPES)
    return m, mbti_style(m)


# 성별표현별 '텍스트 말버릇' 경향 (아주 옅게 — MBTI 가 주 드라이버, 이건 살짝 색만 얹는다).
_VOICE_BY_GENDER = {
    "feminine": "말끝을 부드럽게 맺고 공감 리액션을 조금 더 얹는 편",
    "masculine": "군더더기 없이 담백하고 짧게 끊어 말하는 편",
    "neutral": "담담하고 중립적인 말투",
}


def voice_style(gender: str | None, mbti: str) -> str:
    """성별표현 경향 한 줄. (MBTI 말투와 함께 프롬프트의 '말버릇' 힌트로 쓰인다.)"""
    return _VOICE_BY_GENDER.get((gender or "").strip().lower(), _VOICE_BY_GENDER["neutral"])


# ============================================================
#  얼굴 속성 → 겉모습 설명 (실제 이미지에서 파생 → 절대 불일치 없음)
# ============================================================
_ACCESSORY_PHRASE = {
    "안경": "안경 쓴",
    "모자": "모자를 쓴",
    "이어폰": "이어폰을 낀",
}
_ACCESSORY_PRIORITY = ("안경", "모자", "이어폰")  # 한 개만 골라 설명이 장황해지지 않게

_ATTIRE_PHRASE = {
    "후드티": "후드티 차림의",
    "티셔츠": "편한 티셔츠 차림의",
    "셔츠": "셔츠 차림의",
    "니트": "니트 차림의",
    "정장": "정장 차림의",
    "자켓": "자켓 차림의",
    "아웃도어": "아웃도어 차림의",
}
# 옷차림이 뚜렷하지 않을 때(기타) 헤어로 보완.
_HAIR_PHRASE = {
    "단발": "단발머리의",
    "긴머리": "긴 머리의",
    "짧은머리": "짧은 머리의",
    "묶은머리": "머리를 묶은",
    "삭발": "짧게 민 머리의",
}
_GENDER_NOUN = {"feminine": "여성", "masculine": "남성"}


def compose_appearance(entry: dict) -> str:
    """초상 엔트리(중립 외형 속성) → 자연스러운 한국어 겉모습 설명.

    예: '안경 쓴 후드티 차림의 20대 남성', '단발머리의 30대 여성', '30대 남성'.
    쓰는 속성은 전부 role 과 무관한 중립 외형뿐이다(정답 비노출).
    """
    entry = entry or {}
    age = str(entry.get("age_band") or "").strip()
    attire = str(entry.get("attire") or "").strip()
    hair = str(entry.get("hair") or "").strip()
    acc = [a for a in (entry.get("accessories") or []) if a and a != "없음"]
    gender = str(entry.get("gender_presentation") or "").strip().lower()

    parts: list[str] = []
    for pref in _ACCESSORY_PRIORITY:
        if pref in acc:
            parts.append(_ACCESSORY_PHRASE[pref])
            break
    if attire in _ATTIRE_PHRASE:
        parts.append(_ATTIRE_PHRASE[attire])
    elif hair in _HAIR_PHRASE:
        parts.append(_HAIR_PHRASE[hair])

    gnoun = _GENDER_NOUN.get(gender, "")
    tail = (f"{age} {gnoun}".strip()) if (age or gnoun) else ""
    if tail:
        parts.append(tail)

    text = " ".join(p for p in parts if p).strip()
    return text or (age or "차분한 인상")


# ============================================================
#  통합: 스폰 얼굴을 고르고 '겉모습·성별'을 얻는다
# ============================================================
def resolve_identity(role: str | None, tactics: list | None, gender_pref: str,
                     category: str | None, seed: str | None) -> dict | None:
    """스폰 얼굴을 고르고 (성별표현, 겉모습 설명, 초상 asset_id)를 돌려준다.

    매니페스트가 없거나(폴더 폴백 상황) 얼굴을 못 고르면 None → 호출자는 기존
    일반 겉모습으로 폴백한다. seed(스폰 id)가 없으면 매칭을 보장할 수 없어 None.
    """
    if not seed:
        return None
    from app import portraits

    entry = portraits.resolve_portrait_entry(
        role, list(tactics or []), seed,
        gender_presentation=gender_pref, category=category,
    )
    if not entry:
        return None
    return {
        "gender": entry.get("gender_presentation") or gender_pref,
        "appearance": compose_appearance(entry),
        "asset_id": entry.get("asset_id"),
    }
