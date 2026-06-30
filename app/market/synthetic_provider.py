"""
합성 매물 제공자 (기본값).

내장 카탈로그(app/market/catalog.py)만으로 매물 씨앗을 만든다.
  - API 키 불필요, 항상 오프라인 동작.
  - 같은 (카테고리, 인덱스) 조합은 어느 정도 다양하게 변주된다.

이 제공자는 '가상의' 시장 맥락만 만든다. 실제 게시글을 복제하지 않는다.
"""
from __future__ import annotations

from app.market import catalog
from app.market.providers import (
    SOURCE_SYNTHETIC,
    ListingProvider,
    MarketListingSeed,
)


class SyntheticListingProvider(ListingProvider):
    source_type = SOURCE_SYNTHETIC

    def fetch_listings(self, category: str, limit: int = 20) -> list[MarketListingSeed]:
        seeds: list[MarketListingSeed] = []
        for _ in range(max(1, limit)):
            listing = catalog.generate_listing(category, scenario_type="fair")
            seeds.append(
                MarketListingSeed(
                    source_type=SOURCE_SYNTHETIC,
                    category=listing["category"],
                    product_name=listing["product_name"],
                    title_hint=listing["listing_title"],
                    price_hint=listing["listing_price"],
                    market_price_hint=listing["market_price"],
                    condition_hint=listing["condition_label"],
                    common_defects=listing["disclosed_defects"],
                    accessories=listing["accessories"],
                    trade_methods=listing["trade_methods"],
                    region_label=listing["region_label"],
                    trend_tags=[],
                    safety_notes=listing.get("safe_trade_tips", []),
                )
            )
        return seeds
