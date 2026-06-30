"""
app.market — 시장 데이터 어댑터 + 상품 카탈로그.

구성:
  - catalog.py                 상품 카탈로그 + 매물 생성기 (항상 동작, 오프라인)
  - providers.py               ListingProvider 인터페이스 + MarketListingSeed + 팩토리
  - synthetic_provider.py      합성 매물 (기본값)
  - manual_import_provider.py  안전한 CSV/JSON 수동 import (위생처리 필수)
  - trend_cache.py             비식별·집계 트렌드 기반 생성
  - normalizer.py              개인정보 제거 + 정규화

안전/법적 경계:
  실서비스 스크래핑/크롤링은 절대 하지 않는다. 실제 게시글/사용자 정보를 복제하지 않는다.
  프레이밍: "실시장 트렌드를 참고한 가상 NPC/매물 생성".
"""
from __future__ import annotations

from app.market.providers import (
    ListingProvider,
    MarketListingSeed,
    fetch_seeds,
    get_listing_provider,
)

__all__ = [
    "ListingProvider",
    "MarketListingSeed",
    "fetch_seeds",
    "get_listing_provider",
]
