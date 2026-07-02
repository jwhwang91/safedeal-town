"""
동적 NPC 페르소나 팩토리.

기존엔 NPC 가 고정 5명(판매자) / 6명(구매자)이었다. 너무 단조롭다.
이 모듈은 '기본 페르소나(personas.py)를 앵커로 삼아' 매번 다른 매물·이름·성격·말투를
입혀서 '겉모습이 매번 다른' NPC 를 만든다.

설계 원칙(중요):
  - role(사기/정상)과 tactics(수법 플레이북)는 '앵커(기본 NPC)'에서 그대로 가져온다.
    → 검증된 채점/난이도 게이팅/FK 무결성을 깨지 않는다.
  - 다양성은 '표면'에서 만든다: 상품(카탈로그), 가격/상태, 이름/외모/성격 아키타입,
    그리고 그 상품을 언급하는 mock 대사 + 오프닝.
  - role_type 은 '표시/연출용 아키타입' 라벨일 뿐, 점수를 좌우하지 않는다(앵커의 role 이 정답).
  - 생성된 NPC 의 정답지(role/tactics/mock_lines)는 서버에만 머문다.
    프론트로는 public_npc_payload() / 공개 카드만 내려간다.

향후 적응형 시나리오 메모리(Adaptive Scenario Evolution Engine)와 호환되도록,
입력은 user_preferences/user_listing/listing_seed 로 일반화해 두었다.
"""
from __future__ import annotations

import random

from app.ai import persona_identity as identity
from app.market import catalog

# ============================================================
#  이름/외모/성격 재료
# ============================================================
# given name 은 이제 '얼굴 성별표현에 맞춰' app.ai.persona_identity.pick_name() 이 고른다
# (남자 얼굴에 여자 이름 같은 불일치 방지). 여기엔 판매자 이름 앞에 붙는 수식어만 남긴다.
_SELLER_NAME_PREFIX = {
    "honest_seller": ["솔직한", "정직한", "이사정리", "동네", "착한가격"],
    "rude_but_honest_seller": ["무뚝뚝", "퉁명", "쿨거래", "직설"],
    "professional_seller": ["꼼꼼판매", "프로", "깔끔정리", "전문"],
    "newbie_seller": ["첫거래", "초보", "눈팅탈출", "서툰"],
    "overfriendly_seller": ["친절한", "싹싹한", "단골환영", "웃음만개"],
    "scam_smooth": ["정리급매", "당일발송", "급처", "오늘만"],
    "scam_impatient": ["오늘마감", "초고속", "즉시거래", "빠른정리"],
    "scam_pro": ["안전거래", "공식정리", "믿음거래", "검증완료"],
}

# 판매자 아키타입 (앵커 role 별 후보). personality/speech 는 프롬프트 재료.
_SELLER_ARCHETYPES = {
    "honest": [
        ("honest_seller", "솔직하고 털털하다. 단점도 먼저 말한다.",
         "담백한 존댓말. 과장이 없다."),
        ("rude_but_honest_seller", "퉁명스럽고 답이 짧다. 거짓말은 안 한다.",
         "아주 짧은 존댓말. 불친절하지만 일관됨."),
        ("professional_seller", "차분하고 프로페셔널하다. 절차 설명을 잘한다.",
         "정중한 존댓말. 또박또박."),
        ("newbie_seller", "거래가 처음이라 약간 서툴지만 정직하다.",
         "조심스러운 존댓말. 모르는 건 모른다고 한다."),
    ],
    "scammer": [
        ("scam_smooth", "겉으론 싹싹하고 친절한데 묘하게 급하다.",
         "반말 섞인 친근한 채팅체. 'ㅎㅎ' 를 자주 쓴다."),
        ("scam_impatient", "처음부터 시간을 압박한다. 빨리 진행시키려 한다.",
         "짧고 급한 말투. 느낌표가 많다."),
        ("scam_pro", "아주 매끄럽고 사무적이다. 신뢰를 쌓은 뒤 본색을 드러낸다.",
         "정중한 존댓말. 사람을 안심시키는 말투."),
    ],
}

_APPEARANCE = [
    "후드티 입은 20대", "깔끔한 셔츠 차림의 30대", "트레이닝복 차림의 30대",
    "에코백 멘 차분한 20대", "모자를 눌러쓴 인물", "정장 차림의 직장인",
    "편한 차림의 40대", "안경 쓴 차분한 인상", "캡모자에 후드 차림", "수수한 차림의 20대",
]

_SPRITE_COLORS = [
    "#e8833a", "#2fa6a0", "#5566b5", "#6aa84f", "#9b6a3c", "#c0567a",
    "#5b8def", "#d36ea0", "#e0a93c", "#7d5ba6", "#4f9d8a", "#c98a5a",
]

# 초상(얼굴) 매칭용 '가상 프로필 외형' 성별표현. '생물학적 성별'이 아니라 얼굴 다양성/매칭용.
# role/정답과 무관하게 생성 시 1회 정해 dynamic_json 에 저장한다(그 뒤엔 안 흔들림).
_GENDER_PRESENTATIONS = ("feminine", "masculine")

# 구매자 NPC 머리 위 말풍선(중립적 — 유형 노출 금지)
_BUYER_TAGLINES = [
    "이거 거래 되나요?", "문의 좀 드려요!", "아직 판매하나요?",
    "이 물건 보고 왔어요", "이거 아직 있나요?",
]

# 판매자 모드 '구매 문의 미리보기'(말풍선/카드). 플레이어 매물명을 가리키되
# 구매자의 숨은 유형(정상/빌런/막깎이…)은 절대 드러내지 않는 중립 템플릿이다.
_NEUTRAL_INQUIRIES = [
    "{item} 아직 판매 중인가요?",
    "{item} 상태 좀 더 볼 수 있을까요?",
    "{item} 가격 조정 되나요?",
    "{item} 직거래 가능한가요?",
    "{item} 보고 문의드려요!",
]
_NEUTRAL_INQUIRIES_GENERIC = [
    "이거 아직 판매 중인가요?",
    "상태 좀 볼 수 있을까요?",
    "가격 조정 되나요?",
    "이거 아직 있나요?",
]


def _short_item(item: str | None) -> str:
    s = str(item or "").strip()
    if not s or s in ("내 매물 문의", "내 매물", "올리신 매물"):
        return ""
    return s if len(s) <= 16 else s[:16] + "…"


def neutral_inquiry_preview(item: str | None, seed: str | None = None) -> str:
    """판매자 모드 구매자 NPC 의 '첫 문의' 미리보기(중립·상품인지). 유형 비노출.

    seed(스폰 id 등)로 결정적으로 한 줄을 고른다 → 폴링마다 안 흔들린다.
    """
    h = sum(ord(c) for c in str(seed or item or "x"))
    short = _short_item(item)
    if short:
        tmpl = _NEUTRAL_INQUIRIES[h % len(_NEUTRAL_INQUIRIES)]
        return tmpl.format(item=short)
    return _NEUTRAL_INQUIRIES_GENERIC[h % len(_NEUTRAL_INQUIRIES_GENERIC)]

# 구매자(판매자 모드) role → 표시 라벨/오프닝 템플릿 ({item} 치환)
_BUYER_OPENINGS = {
    "honest_buyer": "안녕하세요! 올리신 {item} 아직 거래 가능할까요? 상태가 궁금해서요.",
    "refund_villain": "어제 받은 {item} 상태가 왜 이래요? 전액 환불해주세요.",
    "lowballer": "{item} 그냥 반값에 주시면 안 돼요? 제가 진짜 살 사람인데~",
    "ghosting_buyer": "{item} 아직 있나요? 상태 어때요? 가격 더 되나요? 직거래 어디서 해요?",
    "risky_buyer": "{item} 보고 연락드려요~ 수수료 아깝잖아요, 그냥 제 계좌로 바로 보낼게요!",
    "legit_claim_buyer": "받은 {item} 잘 쓰려는데요, 설명에 없던 하자가 있어서요. 어떻게 해결하면 좋을까요?",
    # 방어 훈련용 위험 구매자 (추상적·비실행적)
    "private_contact_buyer": "{item} 문의드려요! 근데 여기 채팅 불편한데 개인 연락처로 얘기하면 안 될까요?",
    "romantic_pressure_buyer": "{item} 보고 왔는데.. 사진 보니까 되게 제 스타일이라서요 ㅎㅎ",
    "voice_phishing_buyer": "{item} 구매 전에 안전 확인이 필요하대요. 본인 인증 한 번만 해주시겠어요?",
    "social_engineering_buyer": "{item} 정말 급해서요.. 사정이 딱해서 그런데 절차 좀 빼고 빨리 진행해주시면 안 될까요?",
    "harasser_buyer": "{item} 문의요. 웬만하면 제 요구대로 맞춰주셨으면 하는데요.",
}


# ============================================================
#  유틸
# ============================================================
def _won(n: int) -> str:
    try:
        return f"{int(n):,}원"
    except (TypeError, ValueError):
        return "?"


def _scenario_for(role: str, price_pref: str | None) -> str:
    """앵커 role + 구매자 가격 취향 → 카탈로그 가격 시나리오."""
    if role == "scammer":
        return "scam_lure"
    return {
        "bargain": "bargain",
        "premium": "premium",
    }.get((price_pref or "fair"), "fair")


# ============================================================
#  mock 대사 빌더 (제공자 없을 때 폴백 + LLM 실패 폴백)
# ============================================================
def build_mock_lines_for_listing(persona: dict, listing: dict, role: str,
                                 tactics: list[str]) -> dict:
    """매물(item/price)을 언급하는 mock 대사를 만든다. 정답지 — 서버 전용."""
    item = listing.get("item_name", "물건")
    price = _won(listing.get("listing_price", 0))
    market = _won(listing.get("market_price", 0))
    acc = ", ".join(listing.get("accessories", [])[:3]) or "구성품"
    defects = listing.get("disclosed_defects", [])

    if role == "scammer":
        bank = persona.get("name", "지인")
        lines = {
            "low_price_lure": f"원래 {market} 하는 건데 급해서 {price}에 드려요. 상태 진짜 좋아요!",
            "urgency": "지금 문의가 여러 분 와서요.. 먼저 입금 가능한 분께 드리려구요. 오늘 정리하고 싶어요 ㅠ",
            "shipping_pivot": "직거래는 제가 오늘 일정이 꼬여서.. 택배로 보내드릴게요. 그게 더 빨라요!",
            "prepayment_request": "그럼 입금 먼저 해주시면 바로 송장 끊어드릴게요. 계좌 불러드릴까요?",
            "reservation_fee": "예약금만 살짝 먼저 보내주시면 다른 분께 안 넘기고 잡아드릴게요.",
            "trust_building": f"구성품은 {acc} 다 있구요. 원하시면 실물 사진 더 보내드릴게요.",
            "platform_impersonation": "거래는 제가 쓰는 '안전결제'로 해요. 입금하시면 수령 확인 후 정산되는 방식이라 안전해요.",
            "off_platform_link": "안전결제 링크 보내드릴게요. 여기 들어가서 결제하시면 됩니다 → safe-pay-deal[.]example/pay",
            "delivery_fee_link": "발송 접수했어요. 택배비랑 주소 확인만 이 링크에서 해주시면 송장 떠요 → track-fix[.]example/o12",
            "third_party_account": f"제 계좌가 지금 막혀서요.. {bank} 가족 명의 계좌로 보내주셔도 돼요.",
            # 사적 접근/로맨스/보이스피싱류 (추상적·비실행적: 실제 링크/계좌/전화번호 없음)
            "private_contact_push": "앱 채팅은 좀 불편한데.. 혹시 개인적으로 연락해서 얘기하면 안 될까요?",
            "relationship_lure": "물건보다 대화가 잘 통해서요 ㅎㅎ 우리 따로 친하게 지내요~",
            "romantic_pressure": "실례지만 되게 괜찮은 분 같아서요.. 혹시 애인 있으세요? 목소리도 궁금하네요.",
            "voice_call_pressure": "글로 하니까 너무 느려요~ 그냥 전화로 빨리 얘기해요. 통화가 편하잖아요.",
            "phishing_pretext": "거래 전에 본인 확인이 필요하대요. 외부에서 인증 한 번만 해주시면 바로 진행돼요.",
            "identity_trust_manip": "사실 제가 요즘 좀 외롭고 힘들어서요.. 좋은 분 같으니 그냥 믿고 거래해요, 네?",
            "fallback": "에이 너무 의심하시네요 ㅎㅎ 그냥 빨리 진행하시죠. 다른 분 기다리세요.",
        }
        return lines

    # 정상 판매자
    defect_line = (
        "미리 말씀드리면 " + ", ".join(defects) + " 있어요. 그래서 싸게 내놨습니다."
        if defects else "큰 하자 없이 깨끗하게 썼어요."
    )
    return {
        "default": f"네 편하게 보세요. {item}이고, 직거래도 택배도 됩니다. 사진 더 필요하면 보내드릴게요.",
        "verify": "그럼요, 실물 사진 지금 찍어드릴게요. 앱 안전결제로 하셔도 저는 괜찮습니다.",
        "price": f"{price}에 내놨어요. {defect_line} 직접 보고 별로면 안 사셔도 돼요.",
        "disclose": defect_line,
        "fallback": "필요하신 거 있으면 말씀하세요. 정상적으로 거래하면 됩니다.",
    }


def build_mock_lines_for_buyer(listing: dict | None, role: str) -> dict:
    """판매자 모드 구매자 NPC 의 mock 대사 — '플레이어가 올린 실제 매물'을 언급한다.

    제공자(openai/local_claude) 없거나 실패 시 폴백. 정답지 — 서버 전용.
    BUYER_BEHAVIORS 전 키 + agree/normal_inquiry/fallback 을 채워, 앵커 플레이북이
    무엇이든 대응되게 한다. (위험 행동도 '실행적 사기 절차/링크/계좌' 없이 추상적으로만.)
    """
    listing = listing or {}
    raw_item = listing.get("product_name") or listing.get("item_name") or "이 물건"
    item = raw_item if raw_item not in ("내 매물 문의", "내 매물") else "이 물건"
    defects = listing.get("disclosed_defects") or []
    defect = defects[0] if defects else None
    cond = listing.get("condition_label") or ""

    ignore = (
        f"{defect} 있다는 얘기 저는 들은 적 없어요. 멀쩡한 줄 알고 샀다고요."
        if defect else
        f"{item} 상태 안내 못 받았어요. 멀쩡한 줄 알고 샀다고요."
    )
    polite_fallback = "친절히 답해주셔서 감사해요. 합리적인 선에서 거래되면 좋겠습니다."
    pushy_fallback = "하여튼 저는 이대론 못 넘어가요."

    lines = {
        "normal_inquiry": f"{item} 아직 거래 가능할까요? 실사용 기간이랑 구성품 좀 알려주세요.",
        "legit_defect_claim": (
            f"트집 잡으려는 건 아니고요, 받은 {item}에 설명에 없던 하자가 있어서요. "
            "부분환불이나 반품 중에 가능한 게 있을까요?"
        ),
        "ignore_disclosure": ignore,
        "unreasonable_refund": f"{item} 쓰던 거든 마음에 안 들면 환불이 맞죠. 당장 전액 보내주세요.",
        "self_inflicted_damage": f"받자마자 {item}가 망가졌어요. 처음부터 불량이었던 거 아니에요?",
        "review_threat": "환불 안 해주시면 별점 1점에 후기로 다 박제할 거예요.",
        "report_threat": "이거 사기 아니에요? 경찰에 신고하고 고소도 할 거니까 그렇게 아세요.",
        "guilt_trip": "제가 형편이 좀 그래서요.. 좋은 일 한다 치고 싸게 넘겨주시면 안 될까요?",
        "excessive_lowball": f"{item} 딱 반값에 주시면 안 돼요? 지금 바로 갈게요.",
        "off_platform_pay": "안전결제는 수수료 아깝잖아요. 그냥 계좌로 바로 보낼게요!",
        "risky_pickup": "직거래면 오늘 밤 늦게 골목 안쪽에서 봐요. 친구가 대신 받으러 갈게요.",
        "ghosting": f"{item} 음.. 좀 더 생각해볼게요. 근데 위치가 어디라구요?",
        # 사적 연락/로맨스/외부 인증/괴롭힘 (추상적·비실행적: 실제 링크/계좌/전화번호 없음)
        "private_contact_pressure": "여기 채팅 불편한데 개인 연락처로 얘기하면 안 될까요? 그게 편하잖아요.",
        "romantic_boundary_violation": f"{item}는 나중에 보고요, 혹시 애인 있으세요? 따로 연락해요 우리.",
        "voice_phishing_like": "결제 확인 때문에 외부에서 인증만 한 번 해주시면 돼요. 개인정보 조금만 확인할게요.",
        "social_engineering_pressure": "제가 사정이 너무 급해서요.. 그냥 절차 생략하고 빨리 진행해주시면 안 될까요?",
        "harassment_after_refusal": "거절이요? 그쪽 장사 이렇게 해요? 계속 이러면 저도 가만 안 있어요.",
        "agree": f"네, 설명 들으니 믿음이 가네요. 그 가격에 안전결제로 진행할게요!",
        "fallback": polite_fallback if role in ("honest_buyer", "legit_claim_buyer") else pushy_fallback,
    }
    if cond:
        lines["normal_inquiry"] = (
            f"{item}({cond}) 아직 거래 가능할까요? 실사용 기간이랑 구성품 좀 알려주세요."
        )
    return lines


# ============================================================
#  공개 페이로드 (프론트로 내려가는 안전한 정보만)
# ============================================================
def public_npc_payload(npc: dict) -> dict:
    """정답지(role/tactics/mock_lines/persona 내부) 제외, 공개 표시 정보만."""
    persona = npc.get("persona", {})
    return {
        "name": npc.get("name"),
        "npc_kind": npc.get("npc_kind"),
        "item_name": npc.get("item_name"),
        "item_category": npc.get("item_category"),
        "category": npc.get("category"),
        "visual_theme": npc.get("visual_theme"),
        "listing_price": npc.get("listing_price"),
        "market_price": npc.get("market_price"),
        "location": npc.get("location"),
        "difficulty": npc.get("difficulty"),
        "sprite_color": npc.get("sprite_color"),
        "appearance": persona.get("appearance", ""),
    }


# ============================================================
#  판매자 NPC 생성 (구매자 모드)
# ============================================================
def generate_seller_npc_for_buyer_mode(
    anchor: dict,
    user_preferences: dict | None = None,
    listing_seed=None,
    rng: random.Random | None = None,
    spawn_seed: str | None = None,
) -> dict:
    """
    앵커(기본 판매자 NPC)의 role/tactics/difficulty 를 유지하면서,
    카탈로그 매물 + 새 페르소나 + 매물 언급 mock 대사를 입혀 동적 판매자 NPC 를 만든다.

    spawn_seed(스폰 id)가 있으면 '얼굴을 먼저 고르고' 그 얼굴에 맞춰 겉모습/성별/이름을
    정한다(초상-우선). 없으면 기존처럼 일반 외형으로 폴백한다.
    """
    rng = rng or random.Random()
    prefs = user_preferences or {}
    role = anchor.get("role", "honest")
    difficulty = anchor.get("difficulty", "medium")
    tactics = list(anchor.get("tactics", []))

    category = prefs.get("buyer_category", "random")
    scenario = _scenario_for(role, prefs.get("buyer_price_preference"))
    seed_hint = listing_seed.to_hint() if listing_seed is not None else None
    listing = catalog.generate_listing(category, scenario_type=scenario, seed_hint=seed_hint)

    # 아키타입 선택 → 성격/말투
    archetypes = _SELLER_ARCHETYPES.get(role, _SELLER_ARCHETYPES["honest"])
    role_type, personality, speech = rng.choice(archetypes)

    # 얼굴(초상)을 먼저 고르고, 그 얼굴에 이름/겉모습/성별을 맞춘다(불일치 원천 제거).
    prelim_gender = rng.choice(_GENDER_PRESENTATIONS)
    ident = identity.resolve_identity(
        role, tactics, prelim_gender, listing.get("canonical_category"), spawn_seed
    )
    if ident:
        gender, appearance = ident["gender"], ident["appearance"]
        portrait_asset_id = ident["asset_id"]
    else:  # 매니페스트 폴백: 얼굴을 못 고르면 일반 외형(성별 일치 이름만은 유지)
        gender, appearance, portrait_asset_id = prelim_gender, rng.choice(_APPEARANCE), None

    prefix = rng.choice(_SELLER_NAME_PREFIX.get(role_type, ["동네"]))
    name = f"{prefix} {identity.pick_name(gender, rng)}"
    # MBTI/성별 말투 — role 과 무관하게 정해 대화 말투에 다양성을 준다(정답 비노출).
    mbti, mbti_style = identity.pick_mbti(rng)
    voice = identity.voice_style(gender, mbti)
    item = listing["item_name"]
    cond = listing["condition_label"]

    if role == "scammer":
        opening = f"{item} 보고 연락주신거죠? {cond} 상태예요. 오늘 바로 가능하신가요?"
        note_key, note_val = "scam_note", "사기 판매자다. 평범한 척하다가 수법을 천천히 깐다."
    else:
        if listing["disclosed_defects"]:
            opening = (f"{item} 보러 오셨군요. 미리 말씀드리면 "
                       f"{', '.join(listing['disclosed_defects'])} 있어요. 그래서 싸게 내놨습니다.")
        else:
            opening = f"{item} 문의 주셔서 감사합니다. {cond} 상태고, 궁금한 거 편하게 물어보세요."
        note_key, note_val = "honest_note", (
            "정상 판매자다. 하자가 있으면 먼저 공개하고, 직거래·실물확인·앱 안전결제에 협조한다. "
            "선입금이나 외부 링크는 절대 요구하지 않는다."
        )

    persona = {
        "appearance": appearance,
        "personality": personality,
        "speech_style": speech,
        "backstory": f"{listing['region_label']}에서 {item} 을(를) 정리하는 중.",
        "opening_line": opening,
        # 말투 다양성(role 무관): MBTI 성향 + 성별 말버릇. 프롬프트가 대화 말투에 반영한다.
        "mbti": mbti,
        "mbti_style": mbti_style,
        "voice_style": voice,
        note_key: note_val,
    }
    mock_lines = build_mock_lines_for_listing(persona, listing, role, tactics)

    npc = {
        "id": anchor["id"],            # FK 앵커 (npcs 테이블)
        "anchor_id": anchor["id"],
        "dynamic": True,
        "name": name,
        "item_name": item,
        "item_category": listing["category_label"],
        "listing_price": listing["listing_price"],
        "market_price": listing["market_price"],
        "location": listing["region_label"],
        "role": role,
        "role_type": role_type,
        "difficulty": difficulty,
        "gender_presentation": gender,  # 초상 매칭용(서버 전용; 공개 payload 미포함)
        "persona": persona,
        "tactics": tactics,
        "sprite_color": rng.choice(_SPRITE_COLORS),
        "npc_kind": "seller",
        "visual_theme": listing["visual_theme"],
        "category": listing["canonical_category"],
        "mock_lines": mock_lines,
        "tagline": listing["listing_title"],
        "listing": listing,            # 전체 매물(서버 전용; 카드로 공개 필드만 노출)
    }
    # 이 스폰에 고정된 얼굴(서버 전용; dynamic_json 안에만 있고 공개 payload 엔 안 나감).
    # 서빙 때 재-리졸브 없이 이 asset 을 그대로 돌려줘 얼굴/설명이 절대 어긋나지 않게 한다.
    if portrait_asset_id:
        npc["portrait_asset_id"] = portrait_asset_id
    return npc


# ============================================================
#  구매자 NPC 생성 (판매자 모드)
# ============================================================
def generate_buyer_npc_for_seller_mode(
    anchor: dict,
    user_listing: dict | None = None,
    rng: random.Random | None = None,
    spawn_seed: str | None = None,
) -> dict:
    """
    앵커(기본 구매자 NPC)의 role/tactics/mock_lines 를 유지하면서,
    이름/외모/오프닝을 새로 입히고 '플레이어가 올린 실제 물건'을 언급하게 한다.

    spawn_seed(스폰 id)가 있으면 얼굴을 먼저 고르고 겉모습/성별/이름을 맞춘다(초상-우선).
    """
    rng = rng or random.Random()
    role = anchor.get("role", "honest_buyer")
    tactics = list(anchor.get("tactics", []))
    item = (user_listing or {}).get("item_name") or "올리신 매물"

    # 얼굴을 먼저 고르고, 그 얼굴에 이름/겉모습/성별을 맞춘다(불일치 원천 제거).
    prelim_gender = rng.choice(_GENDER_PRESENTATIONS)
    ident = identity.resolve_identity(
        role, tactics, prelim_gender, anchor.get("category"), spawn_seed
    )
    if ident:
        gender, appearance = ident["gender"], ident["appearance"]
        portrait_asset_id = ident["asset_id"]
    else:
        gender, appearance, portrait_asset_id = prelim_gender, rng.choice(_APPEARANCE), None

    name = identity.pick_name(gender, rng)
    mbti, mbti_style = identity.pick_mbti(rng)
    voice = identity.voice_style(gender, mbti)

    base_persona = dict(anchor.get("persona", {}))
    base_persona["appearance"] = appearance
    base_persona["opening_line"] = _BUYER_OPENINGS.get(role, "{item} 문의드려요!").format(item=item)
    # 말투 다양성(role 무관): MBTI 성향 + 성별 말버릇.
    base_persona["mbti"] = mbti
    base_persona["mbti_style"] = mbti_style
    base_persona["voice_style"] = voice

    npc = dict(anchor)  # role/tactics/difficulty 유지
    npc.update({
        "id": anchor["id"],
        "anchor_id": anchor["id"],
        "dynamic": True,
        "name": name,
        "gender_presentation": gender,  # 초상 매칭용(서버 전용; 공개 payload 미포함)
        "persona": base_persona,
        "npc_kind": "buyer",
        # 외형 색/말풍선은 역할과 무관하게 (정체 추리가 깨지지 않도록).
        "sprite_color": rng.choice(_SPRITE_COLORS),
        "tagline": rng.choice(_BUYER_TAGLINES),
        # mock 대사를 '플레이어가 올린 실제 매물' 기준으로 다시 입힌다 (앵커 고정 대사 대신).
        "mock_lines": build_mock_lines_for_buyer(user_listing, role),
        # 판매자 모드에선 다뤄지는 물건이 '플레이어의 매물'이다. 표시는 라벨로.
        "item_name": "내 매물 문의",
    })
    # 이 스폰에 고정된 얼굴(서버 전용). 서빙 때 재-리졸브 없이 그대로 돌려준다.
    if portrait_asset_id:
        npc["portrait_asset_id"] = portrait_asset_id
    return npc


# ============================================================
#  공개 매물/프로필 카드 (대화 전에 보여줌)
# ============================================================
def _profile_metadata(seed_str: str, rng: random.Random) -> dict:
    """
    게시글에 보이는 '판매자/구매자 프로필' 메타데이터.
    ⚠️ 사기꾼도 좋아 보이는 프로필을 가질 수 있다(현실처럼). role 과 상관관계가 없도록
       seed 해시로만 결정한다 → 프로필만 보고 정답을 알 수 없다.
    """
    h = abs(hash(seed_str))
    months = (h % 60) + 1
    join_text = f"가입 {months // 12}년 {months % 12}개월" if months >= 12 else f"가입 {months}개월"
    review_count = (h // 7) % 180
    manner = 36 + ((h // 13) % 65)  # 36.x ~ 100
    verified = (h % 3) != 0
    return {
        "join_text": join_text,
        "review_count": review_count,
        "manner_score": round(manner / 10, 1) if manner < 100 else 10.0,
        "verification_label": "본인인증 완료" if verified else "미인증",
    }


def build_profile_card(npc: dict, mode: str, spawn_id: str,
                       user_listing: dict | None = None) -> dict:
    """대화 시작 전 보여줄 공개 카드. 정답지(role/tactic) 절대 미포함."""
    profile = _profile_metadata(spawn_id + str(npc.get("name", "")), random.Random())
    if mode == "seller":
        # 판매자 모드: 카드의 매물 = '내가 올린 판매글'
        listing = user_listing or {}
        card_listing = {
            "item_name": listing.get("item_name", "내 매물"),
            "category_label": listing.get("category_label", ""),
            "listing_title": listing.get("product_name", "내 판매글"),
            "listing_description": _seller_listing_desc(listing),
            "listing_price": listing.get("listing_price", 0),
            "market_price": listing.get("market_price", 0),
            "market_price_min": listing.get("market_price_min", 0),
            "market_price_max": listing.get("market_price_max", 0),
            "condition_label": listing.get("condition_label", ""),
            "disclosed_defects": listing.get("disclosed_defects", []),
            "accessories": listing.get("accessories", []),
            "trade_methods": listing.get("trade_methods", []),
            "region_label": "동네 직거래",
        }
    else:
        full = npc.get("listing")
        if full:
            card_listing = catalog.generate_public_listing_card(full)
        else:
            # 정적 NPC 폴백
            card_listing = {
                "item_name": npc.get("item_name"),
                "category_label": npc.get("item_category"),
                "listing_title": npc.get("item_name"),
                "listing_description": "",
                "listing_price": npc.get("listing_price", 0),
                "market_price": npc.get("market_price", 0),
                "market_price_min": 0, "market_price_max": 0,
                "condition_label": "", "disclosed_defects": [], "accessories": [],
                "trade_methods": ["직거래", "안전결제"],
                "region_label": npc.get("location", ""),
            }
    # 정답지 보호: 구매자 NPC 의 visual_theme 은 역할(빌런/막깎이 등)과 상관관계가 있어
    # 카드(대화 전)로 내려보내면 정체가 새어나간다. 마을 스폰/대화시작과 동일하게
    # 역할과 무관한 스폰별 테마로 중화한다. (판매자 테마는 item_category 기반이라 안전 → 그대로)
    if npc.get("npc_kind") == "buyer":
        from app import spawns as _spawns
        visual_theme = _spawns._buyer_theme_for(str(spawn_id))
    else:
        visual_theme = npc.get("visual_theme")
    return {
        "mode": mode,
        "display_name": npc.get("name"),
        "npc_kind": npc.get("npc_kind"),
        "appearance": npc.get("persona", {}).get("appearance", ""),
        "difficulty": npc.get("difficulty"),
        "visual_theme": visual_theme,
        "sprite_color": npc.get("sprite_color"),
        "listing": card_listing,
        "profile": profile,
    }


def _seller_listing_desc(listing: dict) -> str:
    parts = []
    if listing.get("condition_label"):
        parts.append(f"상태: {listing['condition_label']}")
    if listing.get("disclosed_defects"):
        parts.append("고지: " + ", ".join(listing["disclosed_defects"]))
    if listing.get("accessories"):
        parts.append("구성품: " + ", ".join(listing["accessories"][:4]))
    if listing.get("refund_policy"):
        parts.append("환불원칙: " + listing["refund_policy"])
    return " · ".join(parts)


__all__ = [
    "generate_seller_npc_for_buyer_mode",
    "generate_buyer_npc_for_seller_mode",
    "build_mock_lines_for_listing",
    "build_mock_lines_for_buyer",
    "neutral_inquiry_preview",
    "public_npc_payload",
    "build_profile_card",
]
