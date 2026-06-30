"""
판매글 한 줄 제목 → 카테고리 추론 (가벼운 휴리스틱).

판매자 모드의 핵심은 '한 줄 판매글 제목'이다(예: "아이폰 14 Pro 128GB 팔아요").
이 모듈은 그 제목에서 브랜드/모델/키워드를 보고 15종 카테고리 중 하나를 추측한다.

설계 원칙:
  - 외부 호출/스크래핑 없음. 순수 로컬 키워드 매칭이라 항상/오프라인 동작.
  - '추론'은 보조 수단이다. 사용자가 카테고리를 직접 고르면 그게 우선이다(수동 우선).
  - 못 맞히면 'random' (= 게임은 그냥 일반 흐름으로 진행).
  - 키워드는 더 구체적인 것부터(노트북 > 스마트폰 > 전자제품 순) 검사해
    '갤럭시북'(노트북)이 '갤럭시'(스마트폰)로 잘못 걸리지 않게 한다.
"""
from __future__ import annotations

import re

from app.market import catalog

# (카테고리, 키워드들) — 위에서부터 순서대로 검사한다. 더 구체적인 카테고리를 먼저.
# 키워드는 소문자/공백제거 기준으로 매칭한다(한글은 그대로).
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("laptop", (
        "맥북", "macbook", "노트북", "랩탑", "laptop", "그램", "gram",
        "갤럭시북", "갤북", "씽크패드", "thinkpad", "아이디어패드", "울트라북", "엘지그램",
    )),
    ("gaming", (
        "닌텐도", "nintendo", "스위치", "switch", "ps5", "ps4", "플스",
        "플레이스테이션", "playstation", "xbox", "엑스박스", "스팀덱", "steamdeck",
        "게임기", "조이콘", "듀얼센스", "그래픽카드", "rtx", "지포스", "게이밍",
    )),
    ("camera", (
        "카메라", "camera", "dslr", "미러리스", "캐논", "canon", "니콘", "nikon",
        "고프로", "gopro", "짐벌", "액션캠", "후지필름", "fujifilm", "라이카",
    )),
    # 웨어러블/태블릿/오디오/주변기기 — '갤럭시'가 스마트폰으로 새기 전에 먼저 거른다.
    ("electronics", (
        "아이패드", "ipad", "갤럭시탭", "갤탭", "태블릿", "에어팟", "airpods",
        "버즈", "buds", "갤럭시워치", "애플워치", "스마트워치", "워치",
        "이어폰", "헤드폰", "스피커", "키보드", "마우스", "모니터", "ssd",
        "외장하드", "충전기", "공유기", "태블릿pc",
    )),
    ("smartphone", (
        "아이폰", "iphone", "갤럭시", "galaxy", "z플립", "z폴드", "폴드", "플립",
        "픽셀", "pixel", "스마트폰", "핸드폰", "휴대폰", "공기계", "자급제",
    )),
    ("camping", (
        "텐트", "tent", "캠핑", "camping", "랜턴", "lantern", "코펠", "버너",
        "화로대", "타프", "tarp", "침낭", "야전침대", "폴딩박스", "아이스박스", "아웃도어",
    )),
    ("beauty", (
        "화장품", "에어랩", "airwrap", "고데기", "드라이기", "향수", "립스틱",
        "파운데이션", "뷰티", "쿠션", "에센스", "세럼", "마스카라",
    )),
    ("books", (
        "도서", "교재", "문제집", "참고서", "전공책", "전공서적", "만화책",
        "소설", "잡지", "수험서", "원서",
    )),
    ("fashion", (
        "패딩", "코트", "자켓", "재킷", "신발", "운동화", "스니커즈", "나이키",
        "nike", "아디다스", "adidas", "구두", "백팩", "핸드백", "지갑", "명품",
        "루이비통", "샤넬", "구찌", "원피스", "청바지", "후드티", "맨투맨", "패션",
        "의류", "가방",
    )),
    ("furniture", (
        "책상", "소파", "쇼파", "침대", "옷장", "서랍", "행거", "식탁", "책장",
        "매트리스", "화장대", "수납장", "가구", "협탁", "스툴",
    )),
    ("sports", (
        "자전거", "헬스", "덤벨", "아령", "골프", "골프채", "테니스", "라켓",
        "스키", "보드", "킥보드", "런닝머신", "요가매트", "축구", "농구", "헬스기구",
    )),
    ("kids", (
        "유아", "아기", "기저귀", "분유", "유모차", "카시트", "아기띠",
        "아동", "어린이", "보행기",
    )),
    ("hobby", (
        "일렉기타", "통기타", "피아노", "드론", "레고", "프라모델", "피규어",
        "보드게임", "낚시", "자수", "뜨개", "악기",
    )),
    ("home", (
        "청소기", "냉장고", "세탁기", "에어컨", "전자레인지", "밥솥", "가습기",
        "공기청정기", "식기세척기", "인덕션", "티비", "로봇청소기", "정수기",
        "전기포트", "선풍기", "가전",
    )),
    # 책/의자 같은 모호어는 위 구체 규칙(camping 의자, books 도서) 다음에만 본다.
    ("books", ("책",)),
    ("furniture", ("의자",)),
]

_SPACE_RE = re.compile(r"\s+")


def infer_category_from_title(title: str | None) -> str:
    """판매글 제목/상품명에서 카테고리(15종 중 하나)를 추론한다. 못 맞히면 'random'.

    예) "아이폰 14 Pro 128GB 팔아요" -> "smartphone"
        "맥북 에어 M1 급처합니다"     -> "laptop"
        "닌텐도 스위치 OLED"          -> "gaming"
        "캠핑 의자 2개 세트 팔아요"   -> "camping"
    """
    if not title:
        return "random"
    raw = str(title).lower()
    squashed = _SPACE_RE.sub("", raw)
    for category, keywords in _RULES:
        for kw in keywords:
            if kw in raw or kw in squashed:
                return category
    return "random"


def resolve_seller_category(
    title: str | None,
    explicit_category: str | None,
    *,
    default: str = "electronics",
) -> dict:
    """제목 추론 + 수동 선택을 합쳐 최종 판매 카테고리를 정한다.

    규칙(수동 우선):
      - 사용자가 'random/빈값/기본값(electronics)'이 아닌 구체 카테고리를 골랐으면 그걸 쓴다.
      - 그 외에는 제목 추론 결과를 쓰고, 추론도 실패하면 default.
    반환: {"category": 최종, "inferred": 추론값, "source": "manual"|"inferred"|"default"}
    """
    inferred = infer_category_from_title(title)
    explicit = (explicit_category or "").lower().strip()

    # 수동으로 구체 카테고리를 골랐으면 우선한다. (default/electronics 는 '미지정'으로 간주)
    manual_specific = (
        explicit
        and explicit != "random"
        and explicit != default
        and catalog.is_category(explicit)
        and explicit in catalog.PRODUCTS
    )
    if manual_specific:
        return {"category": explicit, "inferred": inferred, "source": "manual"}

    if inferred != "random" and inferred in catalog.PRODUCTS:
        return {"category": inferred, "inferred": inferred, "source": "inferred"}

    # 추론 실패: 사용자가 준 (유효한) 카테고리가 있으면 그걸, 없으면 default.
    if explicit and explicit in catalog.PRODUCTS:
        return {"category": explicit, "inferred": inferred, "source": "manual"}
    return {"category": default, "inferred": inferred, "source": "default"}
