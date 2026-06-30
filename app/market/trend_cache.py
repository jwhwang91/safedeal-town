"""
시장 트렌드 캐시 제공자.

'개별 게시글'이 아니라 '집계된·비식별 시장 트렌드'를 쓴다.
예) 카테고리별 인기 상품명, 평균 가격대, 흔한 하자, 흔한 구성품, 흔한 거래 리스크.

이렇게 하면 실제 게시글을 복제하지 않고도 현실감 있는 시나리오를 만들 수 있다.

저장 형식 (MARKET_TREND_CACHE_PATH, JSON):
{
  "categories": {
    "smartphone": {
      "popular_products": ["아이폰 15 Pro 128GB", ...],
      "avg_price_range": [600000, 1100000],
      "common_defects": ["배터리 성능 저하", "잔기스"],
      "common_accessories": ["박스", "정품 충전기"],
      "common_risks": ["선입금 유도", "외부 링크 결제"],
      "trend_tags": ["수요 높음"]
    }, ...
  }
}

파일이 없으면 카탈로그로부터 기본 트렌드를 합성한다 (항상 동작).
이 모듈은 어떤 외부 호출도 하지 않는다 — 캐시는 '미리 준비된 비식별 데이터'다.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from app.market import catalog
from app.market.providers import (
    SOURCE_TREND,
    ListingProvider,
    MarketListingSeed,
)


class MarketTrendCacheProvider(ListingProvider):
    source_type = SOURCE_TREND

    def __init__(self, cache_path: str | Path | None) -> None:
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict | None = None

    def _load_cache(self) -> dict:
        if self._cache is not None:
            return self._cache
        data = {}
        if self.cache_path and self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        self._cache = data.get("categories", {}) if isinstance(data, dict) else {}
        return self._cache

    def _trend_for(self, category: str) -> dict:
        """캐시에 있으면 그걸, 없으면 카탈로그로 즉석 합성한 트렌드."""
        cache = self._load_cache()
        if category in cache and isinstance(cache[category], dict):
            return cache[category]
        return _synth_trend(category)

    def fetch_listings(self, category: str, limit: int = 20) -> list[MarketListingSeed]:
        rng = random.Random()
        cat = catalog.pick_category(category, rng)
        trend = self._trend_for(cat)
        popular = trend.get("popular_products") or list(catalog.product_names(cat))
        defects = trend.get("common_defects") or []
        accessories = trend.get("common_accessories") or []
        tags = trend.get("trend_tags") or []
        avg = trend.get("avg_price_range") or []
        seeds: list[MarketListingSeed] = []
        for _ in range(max(1, limit)):
            name = rng.choice(popular) if popular else None
            price_hint = None
            market_hint = None
            if len(avg) == 2:
                try:
                    lo, hi = int(avg[0]), int(avg[1])
                    market_hint = rng.randint(min(lo, hi), max(lo, hi))
                    price_hint = int(market_hint * rng.uniform(0.7, 0.95))
                except (TypeError, ValueError):
                    pass
            seeds.append(
                MarketListingSeed(
                    source_type=SOURCE_TREND,
                    category=cat,
                    product_name=name or "중고 물품",
                    title_hint=(name or "중고 물품") + " 판매",
                    price_hint=price_hint,
                    market_price_hint=market_hint,
                    condition_hint="",
                    common_defects=list(defects),
                    accessories=list(accessories),
                    trade_methods=["직거래", "택배", "안전결제"],
                    region_label="",
                    trend_tags=list(tags),
                    safety_notes=trend.get("common_risks", []),
                )
            )
        return seeds


def _synth_trend(category: str) -> dict:
    """카탈로그로부터 비식별 트렌드를 합성한다 (캐시 파일이 없을 때)."""
    cat = category if category in catalog.PRODUCTS else "electronics"
    templates = catalog.PRODUCTS.get(cat, [])
    if not templates:
        return {"popular_products": [], "avg_price_range": [], "common_defects": []}
    lo = min(t["market_price_min"] for t in templates)
    hi = max(t["market_price_max"] for t in templates)
    defaults = catalog._defaults_for(cat)
    return {
        "popular_products": [t["name"] for t in templates],
        "avg_price_range": [lo, hi],
        "common_defects": defaults["defects"],
        "common_accessories": defaults["accessories"],
        "common_risks": ["선입금 유도", "외부 링크 결제", "직거래 후 택배 전환"],
        "trend_tags": [],
    }
