"""
시장 데이터 정규화 + 위생처리(sanitize).

수동 import 한 외부 데이터에서 '개인정보·식별정보·민감정보'를 떼어내고,
게임에 안전하게 쓸 수 있는 일반화된 시장 메타데이터만 남긴다.

매우 중요(안전/법적 경계):
  - 실제 사용자명, 전화번호, 이메일, 정확한 주소, 계좌번호, 실제 URL, 이미지 URL,
    그리고 너무 긴 원문 게시글은 '저장하지 않는다'.
  - 남기는 것은 상품명/카테고리/가격대/상태/구성품/하자 같은 비식별 메타데이터뿐.
  - 이 모듈은 ManualImportProvider 가 외부 CSV/JSON 을 읽을 때 반드시 거친다.
"""
from __future__ import annotations

import re

_MAX_NAME = 60
_MAX_NOTE = 120

# 제거 대상 패턴들 (민감/식별 정보)
# 괄호 안 내용(보통 판매자/연락처/메모) 통째로 제거
_RE_PARENS = re.compile(r"[\(\[（【][^\)\]）】]*[\)\]）】]")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RE_URL = re.compile(r"\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|co\.kr|kr|io)\b", re.IGNORECASE)
# 한국 휴대폰/전화 (010-1234-5678, 01012345678, 02-123-4567 등)
_RE_PHONE = re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b")
# 계좌번호스러운 긴 숫자열 (10자리 이상, 하이픈 포함 가능)
_RE_ACCOUNT = re.compile(r"\b\d[\d-]{8,}\d\b")
# 흔한 한국 은행명 + 뒤따르는 숫자 (계좌 안내 줄 통째로 제거)
_RE_BANK = re.compile(r"(국민|신한|우리|하나|농협|기업|카카오뱅크|토스|새마을|우체국)\s*[은행]?\s*[\d-]{6,}")
# @아이디 / 카톡아이디 류 + "id: xxx" 형태
_RE_HANDLE = re.compile(r"[@#][A-Za-z0-9_\.]{2,}|\b(?:id|아이디|카톡|카카오)\s*[:：]?\s*[A-Za-z0-9_\.]{2,}", re.IGNORECASE)
# "판매자/구매자/성함/이름/닉네임(여러 개 겹쳐도) + 이름(한글 또는 영문)" → 통째로 제거
_RE_NAME = re.compile(
    r"(?:(?:판매자|구매자|보내는\s*사람|받는\s*사람|성함|이름|닉네임)\s*[:：]?\s*)+"
    r"([가-힣]{2,4}|[A-Za-z][A-Za-z.]+(?:\s+[A-Za-z.]+)?)"
)
# 입금/계좌/명의 안내 키워드 + 뒤따르는 토큰
_RE_PAYINFO = re.compile(r"(입금|계좌|명의)\s*[:：]?\s*[가-힣A-Za-z0-9\- ]{0,16}")
# 주소 지번/상세번지 (예: 123-45, 12-3) — 동 단위까지만 남긴다
_RE_LOTNO = re.compile(r"\b\d{1,4}-\d{1,4}\b")
# 건물 상세 (동/호/층/번지) — 정확한 거주지 식별 제거 (예: 101동 205호)
_RE_UNIT = re.compile(r"\d+\s*(동|호|층|번지)")
# 제어문자
_RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# 카테고리 자유표기 → 표준 카테고리 매핑 (느슨하게)
_CATEGORY_ALIASES = {
    "전자": "electronics", "전자제품": "electronics", "가전": "home",
    "폰": "smartphone", "스마트폰": "smartphone", "핸드폰": "smartphone", "휴대폰": "smartphone",
    "노트북": "laptop", "랩탑": "laptop",
    "게임": "gaming", "게임기": "gaming", "콘솔": "gaming",
    "카메라": "camera", "캠핑": "camping", "아웃도어": "camping",
    "뷰티": "beauty", "화장품": "beauty", "미용": "beauty",
    "생활": "home", "생활가전": "home", "주방": "home",
    "가구": "furniture", "패션": "fashion", "의류": "fashion", "옷": "fashion",
    "신발": "fashion", "잡화": "fashion",
    "도서": "books", "책": "books", "유아": "kids", "유아동": "kids", "아동": "kids",
    "스포츠": "sports", "운동": "sports", "취미": "hobby",
}


def strip_personal(text: str | None) -> str:
    """문자열에서 개인정보/식별정보(이름/전화/이메일/주소/계좌/URL/핸들)를 제거하고 길이를 제한한다."""
    if not text:
        return ""
    s = str(text)
    s = _RE_CONTROL.sub(" ", s)
    s = _RE_PARENS.sub(" ", s)   # 괄호 안 메모(연락처/판매자 등) 통째로 제거
    s = _RE_EMAIL.sub("", s)
    s = _RE_URL.sub("", s)
    s = _RE_BANK.sub("", s)
    s = _RE_PAYINFO.sub("", s)
    s = _RE_NAME.sub("", s)
    s = _RE_HANDLE.sub("", s)
    s = _RE_ACCOUNT.sub("", s)
    s = _RE_PHONE.sub("", s)
    s = _RE_UNIT.sub("", s)       # 건물 동/호/층 제거 (정확한 거주지 식별 방지)
    s = _RE_LOTNO.sub("", s)      # 주소 지번 제거 → 동 단위까지만
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def clean_name(text: str | None) -> str:
    return strip_personal(text)[:_MAX_NAME].strip()


def clean_note(text: str | None) -> str:
    return strip_personal(text)[:_MAX_NOTE].strip()


def normalize_category(raw: str | None) -> str:
    """자유표기 카테고리를 표준 카테고리로. 모르면 'random'."""
    from app.market import catalog

    c = (raw or "").strip().lower()
    if not c:
        return "random"
    if c in catalog.CATEGORIES:
        return c
    for ko, mapped in _CATEGORY_ALIASES.items():
        if ko in c:
            return mapped
    return "random"


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        # "1,200,000원", "120000" 등에서 숫자만 추출
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else None
    except (TypeError, ValueError):
        return None


def _to_list(value, limit: int = 5) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [clean_name(v) for v in value]
    else:
        items = [clean_name(p) for p in re.split(r"[,/|]", str(value))]
    return [i for i in items if i][:limit]


def normalize_row(row: dict) -> dict | None:
    """
    외부에서 들어온 한 행(dict)을 정규화한 seed 재료 dict 로 변환한다.
    개인정보는 전부 제거되고, 비식별 시장 메타데이터만 남는다.
    상품명이 비면 None (버린다).
    """
    if not isinstance(row, dict):
        return None
    product_name = clean_name(
        row.get("product_name") or row.get("name") or row.get("title")
    )
    if not product_name:
        return None
    category = normalize_category(row.get("category") or row.get("cat"))
    return {
        "category": category,
        "product_name": product_name,
        "title_hint": clean_note(row.get("title") or row.get("title_hint")) or product_name,
        "price_hint": _to_int(row.get("price") or row.get("price_hint")),
        "market_price_hint": _to_int(row.get("market_price") or row.get("market_price_hint")),
        "condition_hint": clean_name(row.get("condition") or row.get("condition_hint")),
        "common_defects": _to_list(row.get("common_defects") or row.get("defects")),
        "accessories": _to_list(row.get("accessories") or row.get("included")),
        "trade_methods": _to_list(row.get("trade_methods") or row.get("trade"), limit=3),
        "region_label": clean_name(row.get("region") or row.get("region_label")),
        "trend_tags": _to_list(row.get("trend_tags") or row.get("tags")),
        # safety_notes 는 원문에서 끌어오지 않는다 (원문 게시글을 복제하지 않기 위함).
        "safety_notes": [],
    }
