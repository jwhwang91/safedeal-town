"""
상품 카탈로그 + 매물 생성기.

이 파일이 "동적 매물의 설계도"다.
기존엔 NPC 가 닌텐도 스위치/캠핑의자/아이폰 처럼 고정 물건만 팔았다. 너무 단조롭다.
여기서는 카테고리별로 '여러' 상품 템플릿을 정의하고, 시나리오(정상/사기/프리미엄 등)에
맞춰 가격·상태·하자·구성품을 변주해 '매번 다른' 매물을 만들어낸다.

중요(안전/법적 경계):
  - 여기 데이터는 전부 '가상의, 일반화된' 시장 맥락이다.
  - 실제 당근/번개장터 등의 게시글/사용자/이미지/주소를 복제하지 않는다.
  - 외부 스크래핑은 절대 하지 않는다 (app/market/providers.py 주석 참고).

반환하는 listing dict 는 '정답지'를 담지 않는다. 페르소나 팩토리(persona_factory)가
역할(사기/정상)을 따로 입혀서 NPC 를 완성한다.
"""
from __future__ import annotations

import random
from typing import Iterable

# ============================================================
#  카테고리 정의
# ============================================================
# 게임 카테고리(15종) → 캔버스 그림용 표준 카테고리(부스 소품) 매핑.
# sprites.js 가 *_booth 테마를 보고 좌판 소품을 다르게 그린다.
CATEGORIES = [
    "electronics", "smartphone", "laptop", "gaming", "camera",
    "camping", "beauty", "home", "furniture", "fashion",
    "books", "kids", "sports", "hobby", "random",
]

# 실제 매물을 만들 수 있는 카테고리 (random 은 이 중에서 고른다)
_REAL_CATEGORIES = [c for c in CATEGORIES if c != "random"]

CANONICAL_CATEGORY = {
    "electronics": "electronics", "smartphone": "electronics",
    "laptop": "electronics", "gaming": "electronics", "camera": "electronics",
    "camping": "camping", "beauty": "beauty",
    "home": "home", "furniture": "home",
    "fashion": "fashion", "books": "books",
    "kids": "general", "sports": "general", "hobby": "general",
    "random": "general",
}

_THEME_BY_CANONICAL = {
    "electronics": "electronics_booth",
    "beauty": "beauty_booth",
    "camping": "camping_booth",
    "home": "home_booth",
    "fashion": "fashion_booth",
    "books": "books_booth",
    "general": "general_booth",
}

# 카테고리 한국어 라벨 (UI/매물 표시용)
CATEGORY_LABEL = {
    "electronics": "전자제품", "smartphone": "스마트폰", "laptop": "노트북",
    "gaming": "게임", "camera": "카메라", "camping": "캠핑용품", "beauty": "뷰티",
    "home": "생활/가전", "furniture": "가구", "fashion": "패션", "books": "도서",
    "kids": "유아동", "sports": "스포츠", "hobby": "취미", "random": "랜덤",
}

# 상태(컨디션) 키 → 라벨. 판매자 셋업/매물 카드 공용.
CONDITION_LABEL = {
    "new_sealed": "새상품 (미개봉)",
    "like_new": "거의 새것 (S급)",
    "lightly_used": "사용감 적음 (A급)",
    "used": "사용감 있음 (B급)",
    "defect_disclosed": "하자 고지",
    "parts_missing": "구성품 일부 없음",
}

TRADE_METHODS = ["직거래", "택배", "안전결제"]

# 판매자 셋업: 준비한 증거 옵션
PROOF_OPTIONS = [
    {"key": "photos", "label": "실물 사진"},
    {"key": "video", "label": "작동 영상"},
    {"key": "serial", "label": "시리얼/모델명 사진"},
    {"key": "receipt", "label": "구매 영수증"},
    {"key": "defect_closeup", "label": "하자 클로즈업 사진"},
]
PROOF_LABEL = {o["key"]: o["label"] for o in PROOF_OPTIONS}

# 구매자 위시리스트: 가격 민감도 / 선호 거래 방식
PRICE_PREFERENCES = [
    {"key": "bargain", "label": "가성비 우선"},
    {"key": "fair", "label": "적정 시세"},
    {"key": "premium", "label": "상태/프리미엄 우선"},
]
TRADE_PREFERENCES = [
    {"key": "direct", "label": "직거래"},
    {"key": "delivery", "label": "택배"},
    {"key": "safepay", "label": "안전결제"},
    {"key": "any", "label": "상관없음"},
]

# 동네 라벨 후보 (가상의 일반 지역명 — 실제 게시글의 정확한 주소가 아님)
_REGION_LABELS = [
    "수원 영통구", "안산 단원구", "성남 분당구", "용인 수지구", "서울 관악구",
    "고양 일산동구", "인천 연수구", "부천 원미구", "대전 유성구", "청주 흥덕구",
    "화성 동탄", "남양주 다산", "김포 풍무동", "광명 철산동", "안양 평촌",
]


# ============================================================
#  카테고리별 기본값 (proof/팁/구성품/하자) — 상품이 비우면 이걸 쓴다
# ============================================================
_CANONICAL_DEFAULTS = {
    "electronics": {
        "accessories": ["박스", "정품 충전기", "케이블"],
        "defects": ["잔기스", "배터리 성능 저하", "모서리 눌림"],
        "proof": ["실물 사진(전원 켠 상태)", "시리얼/모델명 사진", "구성품 전체 사진"],
        "tips": ["전원이 켜지는지 영상으로 확인", "정품/시리얼 확인", "직거래 시 현장에서 작동 테스트"],
    },
    "camping": {
        "accessories": ["수납가방", "설명서", "부속품"],
        "defects": ["사용감", "보관 중 생긴 얼룩", "야외 사용 흔적"],
        "proof": ["펼친 상태 실물 사진", "사용 횟수 안내", "구성품 사진"],
        "tips": ["사용 횟수/보관 상태 확인", "부피·무게가 크면 직거래 동선 확인"],
    },
    "beauty": {
        "accessories": ["박스", "구성 노즐", "충전 거치대"],
        "defects": ["사용감", "잔여 사용 흔적", "노즐 마모"],
        "proof": ["정품 인증 사진", "작동 영상", "구성품 사진"],
        "tips": ["정품 여부 확인", "위생 상태/사용 횟수 확인"],
    },
    "home": {
        "accessories": ["설명서", "리모컨", "부속품"],
        "defects": ["사용감", "잔기스", "소모품 교체 필요"],
        "proof": ["작동 영상", "실물 사진", "구성품 사진"],
        "tips": ["작동 확인", "부피 큰 가구는 직거래/운반 동선 확인"],
    },
    "fashion": {
        "accessories": ["보증서", "더스트백", "택"],
        "defects": ["착용감", "보풀", "변색", "오염"],
        "proof": ["실물 택/라벨 사진", "정품 보증서 사진", "착용/사이즈 사진"],
        "tips": ["정품/사이즈 확인", "오염·하자 부위 클로즈업 요청"],
    },
    "books": {
        "accessories": ["부록", "CD", "정답지"],
        "defects": ["필기 흔적", "변색", "모서리 닳음"],
        "proof": ["속지 상태 사진", "필기 여부 사진"],
        "tips": ["필기/낙서 여부 확인", "에디션/쇄 확인"],
    },
    "general": {
        "accessories": ["박스", "구성품"],
        "defects": ["사용감", "잔기스"],
        "proof": ["실물 사진", "구성품 사진"],
        "tips": ["상태/구성품 확인", "직거래 시 현장 확인"],
    },
}


def _p(name, pmin, pmax, weight=1, defects=None, accessories=None, proof=None):
    """상품 템플릿 한 줄 헬퍼. 비운 필드는 카테고리 기본값으로 채워진다."""
    return {
        "name": name,
        "market_price_min": pmin,
        "market_price_max": pmax,
        "weight": weight,
        "common_defects": defects,
        "typical_accessories": accessories,
        "proof_requests": proof,
    }


# ============================================================
#  상품 템플릿 (카테고리별)
# ============================================================
PRODUCTS: dict[str, list[dict]] = {
    "electronics": [
        _p("AirPods Max", 380_000, 560_000, 2),
        _p("AirPods Pro 2", 180_000, 280_000, 3),
        _p("iPad Air 5", 480_000, 680_000, 2),
        _p("iPad Pro 11", 700_000, 1_050_000, 1),
        _p("LG 27인치 게이밍 모니터", 180_000, 320_000, 2),
        _p("기계식 키보드 (적축)", 55_000, 110_000, 3),
        _p("무선 마우스 (로지텍)", 30_000, 80_000, 3),
        _p("포터블 모니터 15.6", 120_000, 220_000, 2),
        _p("드로잉 태블릿 (와콤)", 90_000, 200_000, 2),
        _p("블루투스 스피커", 40_000, 130_000, 2),
        _p("외장 SSD 1TB", 70_000, 140_000, 2),
        _p("스마트워치 (갤럭시워치)", 120_000, 260_000, 2),
    ],
    "smartphone": [
        _p("아이폰 15 Pro 128GB", 850_000, 1_150_000, 2),
        _p("아이폰 14 128GB", 600_000, 820_000, 3),
        _p("갤럭시 S24 256GB", 700_000, 980_000, 2),
        _p("갤럭시 Z플립5", 550_000, 850_000, 2),
        _p("아이폰 13 mini", 380_000, 560_000, 2),
        _p("갤럭시 S23 256GB", 480_000, 700_000, 2),
        _p("아이폰 SE 3세대", 280_000, 420_000, 2),
    ],
    "laptop": [
        _p("MacBook Air M1", 600_000, 850_000, 3),
        _p("MacBook Pro 14 M2", 1_500_000, 2_100_000, 1),
        _p("그램 16 (2023)", 900_000, 1_350_000, 2),
        _p("갤럭시북3 프로", 850_000, 1_250_000, 2),
        _p("LG 울트라PC", 450_000, 700_000, 2),
        _p("맥북 에어 M2", 950_000, 1_350_000, 2),
    ],
    "gaming": [
        _p("닌텐도 스위치 OLED", 230_000, 330_000, 3),
        _p("플레이스테이션 5", 480_000, 650_000, 2),
        _p("Xbox Series S", 250_000, 380_000, 2),
        _p("스팀덱 OLED", 550_000, 780_000, 1),
        _p("닌텐도 스위치 라이트", 130_000, 200_000, 2),
        _p("듀얼센스 컨트롤러", 45_000, 80_000, 3),
        _p("게이밍 헤드셋", 50_000, 130_000, 2),
    ],
    "camera": [
        _p("소니 ZV-E10 미러리스", 500_000, 750_000, 2),
        _p("후지필름 X-T30", 600_000, 900_000, 2),
        _p("캐논 EOS R50", 650_000, 950_000, 2),
        _p("DJI 오즈모 포켓3", 450_000, 620_000, 2),
        _p("고프로 12", 350_000, 520_000, 2),
        _p("니콘 단렌즈 35mm", 200_000, 380_000, 2),
    ],
    "camping": [
        _p("캠핑 의자 2개 세트", 30_000, 80_000, 3),
        _p("4인용 텐트", 90_000, 220_000, 2),
        _p("침낭 (동계용)", 50_000, 130_000, 2),
        _p("LED 랜턴 세트", 25_000, 70_000, 3),
        _p("캠핑 테이블 (롤테이블)", 40_000, 110_000, 2),
        _p("아이스박스 25L", 35_000, 90_000, 2),
        _p("감성 가스등", 30_000, 80_000, 2),
        _p("캠핑 웨건", 70_000, 160_000, 2),
        _p("파워뱅크 (포터블 파워)", 180_000, 420_000, 1),
        _p("타프 + 폴대 세트", 60_000, 140_000, 2),
    ],
    "beauty": [
        _p("다이슨 에어랩 컴플리트", 280_000, 480_000, 2),
        _p("다이슨 슈퍼소닉 드라이어", 250_000, 420_000, 2),
        _p("LED 마스크", 150_000, 350_000, 2),
        _p("갈바닉 미용기기", 80_000, 200_000, 2),
        _p("전기 면도기 (브라운)", 60_000, 150_000, 2),
        _p("두피 마사지기", 40_000, 110_000, 2),
        _p("고데기 (볼륨매직)", 30_000, 80_000, 3),
    ],
    "home": [
        _p("공기청정기", 120_000, 300_000, 2),
        _p("로봇청소기", 200_000, 500_000, 2),
        _p("에어프라이어", 50_000, 130_000, 3),
        _p("전자레인지", 40_000, 90_000, 2),
        _p("커피머신 (캡슐)", 80_000, 200_000, 2),
        _p("가습기", 30_000, 80_000, 3),
        _p("무선 청소기 (다이슨)", 250_000, 480_000, 2),
        _p("스탠드 선풍기", 30_000, 70_000, 2),
    ],
    "furniture": [
        _p("게이밍/사무용 의자", 80_000, 250_000, 3),
        _p("높이조절 책상", 120_000, 300_000, 2),
        _p("원목 책장 5단", 60_000, 160_000, 2),
        _p("모니터 암", 40_000, 110_000, 3),
        _p("3인용 패브릭 소파", 150_000, 400_000, 1),
        _p("수납장 (서랍형)", 50_000, 130_000, 2),
        _p("행거/옷걸이 선반", 25_000, 70_000, 2),
    ],
    "fashion": [
        _p("숏패딩 (구스다운)", 90_000, 250_000, 2),
        _p("나이키 운동화 270mm", 60_000, 150_000, 3),
        _p("명품 반지갑", 200_000, 500_000, 2),
        _p("백팩 (노스페이스)", 60_000, 140_000, 2),
        _p("기계식 손목시계", 150_000, 600_000, 1),
        _p("후드티 (정품)", 30_000, 90_000, 3),
        _p("데님 자켓", 40_000, 110_000, 2),
        _p("가죽 크로스백", 80_000, 220_000, 2),
    ],
    "books": [
        _p("전공 교재 세트", 30_000, 90_000, 3),
        _p("자격증 수험서 풀세트", 25_000, 70_000, 3),
        _p("만화책 전질", 40_000, 120_000, 2),
        _p("아동 전집", 60_000, 180_000, 2),
        _p("베스트셀러 소설 묶음", 15_000, 45_000, 3),
    ],
    "kids": [
        _p("유아 카시트", 80_000, 220_000, 2),
        _p("아기 유모차 (디럭스)", 150_000, 450_000, 2),
        _p("원목 아기 침대", 70_000, 200_000, 2),
        _p("장난감 블록 대용량", 30_000, 90_000, 3),
        _p("아기 바운서", 40_000, 120_000, 2),
        _p("유아 자전거", 30_000, 80_000, 2),
    ],
    "sports": [
        _p("로드 자전거", 200_000, 600_000, 2),
        _p("입문용 골프 풀세트", 200_000, 500_000, 2),
        _p("덤벨 세트 (조절형)", 60_000, 160_000, 2),
        _p("전동 킥보드", 180_000, 400_000, 2),
        _p("등산화 (고어텍스)", 50_000, 140_000, 2),
        _p("요가매트 + 폼롤러", 20_000, 50_000, 3),
        _p("실내 사이클", 90_000, 250_000, 2),
    ],
    "hobby": [
        _p("입문용 통기타", 50_000, 150_000, 2),
        _p("전자 키보드(피아노)", 80_000, 250_000, 2),
        _p("프라모델 미조립 세트", 40_000, 120_000, 2),
        _p("레고 크리에이터", 60_000, 180_000, 2),
        _p("드론 (입문용)", 90_000, 250_000, 2),
        _p("낚시 릴+로드 세트", 70_000, 200_000, 2),
        _p("보드게임 묶음", 30_000, 80_000, 3),
    ],
}


# ============================================================
#  유틸
# ============================================================
def is_category(category: str | None) -> bool:
    return (category or "").lower() in CATEGORIES


def canonical_of(category: str) -> str:
    return CANONICAL_CATEGORY.get((category or "").lower(), "general")


def theme_for(category: str) -> str:
    return _THEME_BY_CANONICAL.get(canonical_of(category), "general_booth")


def pick_category(wishlist_category: str | None, rng: random.Random) -> str:
    """위시리스트 카테고리를 실제 매물 카테고리로 변환. random/없음 → 전체에서 선택."""
    cat = (wishlist_category or "random").lower()
    if cat == "random" or cat not in PRODUCTS:
        return rng.choice(_REAL_CATEGORIES)
    return cat


def _defaults_for(category: str) -> dict:
    return _CANONICAL_DEFAULTS.get(canonical_of(category), _CANONICAL_DEFAULTS["general"])


def _weighted_pick(templates: list[dict], rng: random.Random) -> dict:
    weights = [max(1, int(t.get("weight", 1))) for t in templates]
    return rng.choices(templates, weights=weights, k=1)[0]


def estimate_market_price(template: dict, rng: random.Random | None = None) -> int:
    """상품 템플릿 시세 추정치(중앙값 부근, 천원 단위 반올림)."""
    rng = rng or random.Random()
    lo, hi = template["market_price_min"], template["market_price_max"]
    mid = (lo + hi) / 2
    # 시세는 중앙값 ±15% 안에서 흔들린다 (동네/상태에 따라 다른 느낌).
    val = mid * rng.uniform(0.9, 1.1)
    return _round_price(val)


def _round_price(val: float) -> int:
    val = max(1000, val)
    if val >= 100_000:
        step = 5_000
    elif val >= 20_000:
        step = 1_000
    else:
        step = 500
    return int(round(val / step) * step)


# 시나리오 타입(persona_factory 가 역할에서 도출) → 가격 배율
#  - scam_lure   : 사기꾼의 초저가 미끼 (시세 대비 매우 낮음)
#  - bargain     : 정상이지만 빠른 처분 (시세보다 다소 낮음)
#  - fair        : 합리적 시세가
#  - premium     : 상태/구성 좋아 시세 상단
_PRICE_MULTIPLIER = {
    "scam_lure": (0.45, 0.62),
    "bargain": (0.68, 0.82),
    "fair": (0.82, 0.95),
    "premium": (0.95, 1.08),
}


def generate_listing_price(template: dict, scenario_type: str, market_price: int,
                           rng: random.Random | None = None) -> int:
    """시나리오에 맞춰 '부른 가격'을 만든다. market_price 기준 배율."""
    rng = rng or random.Random()
    lo, hi = _PRICE_MULTIPLIER.get(scenario_type, _PRICE_MULTIPLIER["fair"])
    return _round_price(market_price * rng.uniform(lo, hi))


# 시나리오 → 상태 후보 가중치. 사기꾼은 '거의 새것'을 내세우고,
# 정상/하자고지형은 솔직하게 사용감/하자를 공개한다.
_CONDITION_WEIGHTS = {
    "scam_lure": {"like_new": 5, "new_sealed": 3, "lightly_used": 2},
    "bargain": {"lightly_used": 4, "used": 3, "defect_disclosed": 2, "like_new": 1},
    "fair": {"lightly_used": 4, "like_new": 3, "used": 2, "defect_disclosed": 1},
    "premium": {"like_new": 4, "new_sealed": 3, "lightly_used": 2},
}


def generate_condition(template: dict, scenario_type: str,
                       rng: random.Random | None = None) -> dict:
    """상태 키 + 공개 하자 목록을 만든다."""
    rng = rng or random.Random()
    weights = _CONDITION_WEIGHTS.get(scenario_type, _CONDITION_WEIGHTS["fair"])
    keys = list(weights.keys())
    cond = rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]

    defaults = _defaults_for(template["category"])
    defect_pool = template.get("common_defects") or defaults["defects"]
    disclosed: list[str] = []
    if cond in ("defect_disclosed", "used", "parts_missing"):
        n = 1 if cond == "used" else rng.randint(1, 2)
        disclosed = rng.sample(defect_pool, min(n, len(defect_pool)))
    elif cond == "lightly_used" and rng.random() < 0.4:
        disclosed = rng.sample(defect_pool, 1)
    return {
        "condition": cond,
        "condition_label": CONDITION_LABEL[cond],
        "disclosed_defects": disclosed,
    }


# ============================================================
#  매물 생성 (핵심)
# ============================================================
_TITLE_TEMPLATES = [
    "{name} {cond} 판매합니다",
    "{name} 급처해요 ({cond})",
    "{name} 상태 좋아요 {cond}",
    "{name} 정리합니다 {cond}",
    "[{region}] {name} {cond}",
]


def generate_listing(
    category: str | None = None,
    *,
    scenario_type: str = "fair",
    seed: str | int | None = None,
    seed_hint: dict | None = None,
) -> dict:
    """
    매물 하나를 만든다. 같은 seed → 같은 매물(결정적).

    seed_hint: MarketListingProvider 가 준 seed(정규화된 시장 맥락)를 일부 반영할 수 있다.
               (product_name/price_hint/condition_hint/common_defects 등) — 없으면 카탈로그로만 생성.
    반환 dict 는 '정답지(role/tactic)'를 담지 않는다.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    cat = pick_category(category, rng)
    canonical = canonical_of(cat)
    templates = PRODUCTS.get(cat, PRODUCTS["electronics"])
    template = dict(_weighted_pick(templates, rng))
    template["category"] = cat

    # seed_hint 로 상품명/가격을 살짝 덮어쓸 수 있다 (수동 import/트렌드 반영).
    if seed_hint:
        if seed_hint.get("product_name"):
            template["name"] = str(seed_hint["product_name"])[:60]
        if seed_hint.get("common_defects"):
            template["common_defects"] = [str(d)[:40] for d in seed_hint["common_defects"]][:4]
        if seed_hint.get("accessories"):
            template["typical_accessories"] = [str(a)[:40] for a in seed_hint["accessories"]][:5]

    market = estimate_market_price(template, rng)
    if seed_hint and seed_hint.get("market_price_hint"):
        try:
            market = _round_price(float(seed_hint["market_price_hint"]))
        except (TypeError, ValueError):
            pass

    listing_price = generate_listing_price(template, scenario_type, market, rng)
    if seed_hint and seed_hint.get("price_hint"):
        try:
            listing_price = _round_price(float(seed_hint["price_hint"]))
        except (TypeError, ValueError):
            pass

    cond = generate_condition(template, scenario_type, rng)
    defaults = _defaults_for(cat)
    accessories = template.get("typical_accessories") or defaults["accessories"]
    proof = template.get("proof_requests") or defaults["proof"]
    tips = defaults["tips"]

    # 거래 방식: 직거래/택배는 거의 항상, 안전결제는 종종 (부피/가격에 따라)
    methods = ["직거래"]
    if rng.random() < 0.85:
        methods.append("택배")
    if rng.random() < 0.7:
        methods.append("안전결제")
    region = rng.choice(_REGION_LABELS)
    name = template["name"]

    title = rng.choice(_TITLE_TEMPLATES).format(
        name=name, cond=cond["condition_label"], region=region
    )
    desc = _build_description(name, cond, accessories, methods, rng)

    return {
        "product_id": f"{cat}:{name}",
        "category": cat,
        "canonical_category": canonical,
        "category_label": CATEGORY_LABEL.get(cat, cat),
        "product_name": name,
        "item_name": name,
        "listing_price": int(listing_price),
        "market_price": int(market),
        "market_price_min": int(template["market_price_min"]),
        "market_price_max": int(template["market_price_max"]),
        "condition": cond["condition"],
        "condition_label": cond["condition_label"],
        "disclosed_defects": cond["disclosed_defects"],
        "accessories": list(accessories),
        "proof_requests": list(proof),
        "safe_trade_tips": list(tips),
        "trade_methods": methods,
        "region_label": region,
        "listing_title": title,
        "listing_description": desc,
        "visual_theme": _THEME_BY_CANONICAL.get(canonical, "general_booth"),
        "trend_tags": list(seed_hint.get("trend_tags", [])) if seed_hint else [],
    }


def _build_description(name, cond, accessories, methods, rng: random.Random) -> str:
    parts = [f"{name} 판매합니다."]
    parts.append(f"상태는 {cond['condition_label']} 입니다.")
    if cond["disclosed_defects"]:
        parts.append("미리 알려드리면 " + ", ".join(cond["disclosed_defects"]) + " 있어요.")
    else:
        parts.append("큰 하자 없이 깨끗하게 사용했어요.")
    if accessories:
        parts.append("구성품: " + ", ".join(accessories[:4]) + ".")
    parts.append("거래는 " + "/".join(methods) + " 가능합니다.")
    return " ".join(parts)


def generate_public_listing_card(listing: dict) -> dict:
    """
    프론트에 내려보낼 '공개 매물 카드'. 정답지(role/tactic/scenario)는 절대 포함하지 않는다.
    시세/가격/상태/구성품/거래방식 등 게시글에 정당히 보이는 정보만.
    """
    return {
        "item_name": listing.get("item_name"),
        "category": listing.get("category"),
        "category_label": listing.get("category_label"),
        "listing_title": listing.get("listing_title"),
        "listing_description": listing.get("listing_description"),
        "listing_price": listing.get("listing_price"),
        "market_price": listing.get("market_price"),
        "market_price_min": listing.get("market_price_min"),
        "market_price_max": listing.get("market_price_max"),
        "condition": listing.get("condition"),
        "condition_label": listing.get("condition_label"),
        "disclosed_defects": listing.get("disclosed_defects", []),
        "accessories": listing.get("accessories", []),
        "trade_methods": listing.get("trade_methods", []),
        "region_label": listing.get("region_label"),
        "visual_theme": listing.get("visual_theme"),
    }


def category_choices() -> list[dict]:
    """프론트 셋업 화면이 쓸 카테고리 목록 (key + 라벨)."""
    return [{"key": c, "label": CATEGORY_LABEL.get(c, c)} for c in CATEGORIES]


def catalog_meta() -> dict:
    """
    프론트 셋업/판매글 UI 가 쓰는 카탈로그 메타데이터.
    각 상품의 평균 시세/흔한 하자/구성품/증거요청을 포함해 '자동완성'을 돕는다.
    """
    products: dict[str, list[dict]] = {}
    for cat, templates in PRODUCTS.items():
        defaults = _defaults_for(cat)
        rows = []
        for t in templates:
            rows.append({
                "name": t["name"],
                "market_price_min": t["market_price_min"],
                "market_price_max": t["market_price_max"],
                "market_price": estimate_market_price({**t, "category": cat}),
                "common_defects": t.get("common_defects") or defaults["defects"],
                "typical_accessories": t.get("typical_accessories") or defaults["accessories"],
                "proof_requests": t.get("proof_requests") or defaults["proof"],
            })
        products[cat] = rows
    return {
        "categories": category_choices(),
        "conditions": [{"key": k, "label": v} for k, v in CONDITION_LABEL.items()],
        "trade_methods": list(TRADE_METHODS),
        "proof_options": PROOF_OPTIONS,
        "price_preferences": PRICE_PREFERENCES,
        "trade_preferences": TRADE_PREFERENCES,
        "products": products,
    }


def product_names(category: str) -> Iterable[str]:
    """해당 카테고리의 대표 상품명들 (판매자 셋업 자동완성 후보용)."""
    cat = (category or "").lower()
    if cat in PRODUCTS:
        return [t["name"] for t in PRODUCTS[cat]]
    return []


def find_template(category: str, name: str) -> dict | None:
    """카테고리+이름으로 상품 템플릿을 찾는다 (판매자 셋업 자동완성용)."""
    cat = (category or "").lower()
    for t in PRODUCTS.get(cat, []):
        if t["name"] == name:
            out = dict(t)
            out["category"] = cat
            defaults = _defaults_for(cat)
            out["common_defects"] = t.get("common_defects") or defaults["defects"]
            out["typical_accessories"] = t.get("typical_accessories") or defaults["accessories"]
            out["proof_requests"] = t.get("proof_requests") or defaults["proof"]
            out["market_price"] = estimate_market_price(out)
            return out
    return None
