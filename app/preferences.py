"""
회원별 마켓 선호/판매글 저장소.

  - 구매자 모드: '오늘 찾는 물건'(위시리스트) — buyer_category / 가격민감도 / 선호 거래방식
  - 판매자 모드: '내 판매글' — 상품/상태/가격/구성품/하자/증거

게임 라우터(setup·preferences·listing), 채팅(판매자 모드 구매자 NPC), 페르소나 팩토리가
모두 이 모듈을 통해 선호/판매글을 읽고 쓴다.

판매글의 자유 입력(상품명/구성품/하자)은 normalizer 로 개인정보를 제거하고 길이를 제한한다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.market import catalog
from app.market import category_infer
from app.market.normalizer import strip_personal

_VALID_PRICE_PREF = {"bargain", "fair", "premium"}
_VALID_TRADE_PREF = {"direct", "delivery", "safepay", "any"}
_VALID_PROOF = set(catalog.PROOF_LABEL.keys())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_short(text, limit: int = 40) -> str:
    return strip_personal(text)[:limit].strip()


def _clean_list(values, limit_items: int, item_len: int = 40) -> list[str]:
    out = []
    for v in (values or []):
        c = _clean_short(v, item_len)
        if c:
            out.append(c)
        if len(out) >= limit_items:
            break
    return out


# ============================================================
#  읽기
# ============================================================
def get_preferences(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(
        "SELECT buyer_category, buyer_price_preference, buyer_trade_preference, "
        "seller_listing_json FROM user_market_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    seller = None
    if row and row["seller_listing_json"]:
        try:
            parsed = json.loads(row["seller_listing_json"])
            if isinstance(parsed, dict):
                seller = parsed
        except (json.JSONDecodeError, TypeError):
            seller = None
    return {
        "buyer_category": (row["buyer_category"] if row else None) or "random",
        "buyer_price_preference": (row["buyer_price_preference"] if row else None) or "fair",
        "buyer_trade_preference": (row["buyer_trade_preference"] if row else None) or "any",
        "seller_listing": seller,
    }


def get_seller_listing(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return get_preferences(conn, user_id)["seller_listing"]


# ============================================================
#  쓰기
# ============================================================
def _upsert(conn, user_id, *, buyer_category=None, price_pref=None,
            trade_pref=None, seller_listing_json=None) -> None:
    """있는 행은 주어진 컬럼만 갱신, 없으면 새로 만든다 (멱등)."""
    existing = conn.execute(
        "SELECT 1 FROM user_market_preferences WHERE user_id = ?", (user_id,)
    ).fetchone()
    now = _now()
    if existing:
        sets, params = [], []
        if buyer_category is not None:
            sets.append("buyer_category = ?"); params.append(buyer_category)
        if price_pref is not None:
            sets.append("buyer_price_preference = ?"); params.append(price_pref)
        if trade_pref is not None:
            sets.append("buyer_trade_preference = ?"); params.append(trade_pref)
        if seller_listing_json is not None:
            sets.append("seller_listing_json = ?"); params.append(seller_listing_json)
        sets.append("updated_at = ?"); params.append(now)
        params.append(user_id)
        conn.execute(
            f"UPDATE user_market_preferences SET {', '.join(sets)} WHERE user_id = ?",
            params,
        )
    else:
        conn.execute(
            "INSERT INTO user_market_preferences "
            "(user_id, buyer_category, buyer_price_preference, buyer_trade_preference, "
            "seller_listing_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, buyer_category or "random", price_pref or "fair",
             trade_pref or "any", seller_listing_json, now),
        )


def save_buyer_preferences(conn, user_id, buyer_category, price_pref, trade_pref) -> dict:
    cat = (buyer_category or "random").lower()
    if not catalog.is_category(cat):
        cat = "random"
    price = price_pref if price_pref in _VALID_PRICE_PREF else "fair"
    trade = trade_pref if trade_pref in _VALID_TRADE_PREF else "any"
    _upsert(conn, user_id, buyer_category=cat, price_pref=price, trade_pref=trade)
    return {
        "buyer_category": cat,
        "buyer_price_preference": price,
        "buyer_trade_preference": trade,
    }


def normalize_seller_listing(req) -> dict:
    """SellerListingRequest → 위생처리된 판매글 dict (파생 필드 포함).

    카테고리는 '한 줄 제목(상품명)'에서 추론하되, 사용자가 구체 카테고리를 직접
    고른 경우 그 선택을 우선한다(수동 우선). 추론도 실패하면 electronics 로 폴백.
    """
    product_name = _clean_short(req.product_name, 60) or "중고 물품"
    resolved = category_infer.resolve_seller_category(
        product_name, req.category, default="electronics"
    )
    cat = resolved["category"]
    if cat not in catalog.PRODUCTS:  # 안전망 (정상적으론 도달 안 함)
        cat = "electronics"
    canonical = catalog.canonical_of(cat)
    condition = req.condition if req.condition in catalog.CONDITION_LABEL else "lightly_used"

    template = catalog.find_template(cat, product_name)
    market_price = int(req.market_price or 0)
    if market_price <= 0:
        if template:
            market_price = int(template["market_price"])
        elif req.listing_price:
            market_price = catalog._round_price(req.listing_price * 1.2)
    market_min = int(template["market_price_min"]) if template else 0
    market_max = int(template["market_price_max"]) if template else 0

    trade_methods = [m for m in (req.trade_methods or []) if m in catalog.TRADE_METHODS]
    if not trade_methods:
        trade_methods = ["직거래", "안전결제"]
    proof = [p for p in (req.proof_prepared or []) if p in _VALID_PROOF]

    return {
        "category": cat,
        "inferred_category": resolved["inferred"],
        "category_source": resolved["source"],
        "canonical_category": canonical,
        "category_label": catalog.CATEGORY_LABEL.get(cat, cat),
        "product_name": product_name,
        "item_name": product_name,
        "condition": condition,
        "condition_label": catalog.CONDITION_LABEL[condition],
        "listing_price": int(req.listing_price or 0),
        "market_price": market_price,
        "market_price_min": market_min,
        "market_price_max": market_max,
        "disclosed_defects": _clean_list(req.disclosed_defects, 8),
        "accessories": _clean_list(req.accessories, 10),
        "trade_methods": trade_methods,
        "refund_policy": _clean_short(req.refund_policy, 200),
        "proof_prepared": proof,
        "proof_labels": [catalog.PROOF_LABEL[p] for p in proof],
        "visual_theme": catalog.theme_for(cat),
    }


def save_seller_listing(conn, user_id, listing: dict) -> dict:
    """판매글 저장 + users.seller_category 를 표준 부스 카테고리로 동기화."""
    _upsert(conn, user_id, seller_listing_json=json.dumps(listing, ensure_ascii=False))
    # 부스 테마/라벨용 coarse 카테고리도 맞춰둔다 (기존 코드와 호환)
    conn.execute(
        "UPDATE users SET seller_category = ?, updated_at = ? WHERE id = ?",
        (listing.get("canonical_category", "general"), _now(), user_id),
    )
    return listing
