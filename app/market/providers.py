"""
시장 데이터 어댑터(Provider) 계층.

게임의 NPC/매물 생성기는 "매물 맥락이 어디서 왔는지" 몰라도 된다.
여기서 MARKET_LISTING_PROVIDER 설정에 따라 실제 소스를 고른다:

  - synthetic     : 내장 카탈로그로 합성 (기본값, 항상 오프라인 동작)
  - manual_import : 개발자가 둔 안전한 CSV/JSON 을 위생처리해서 사용
  - trend_cache   : 비식별·집계된 시장 트렌드로 매물 맥락 생성
  - official_stub : (미구현) 공식 API 자리표시자 — 실제 호출/스크래핑 없음

매우 중요(안전/법적 경계):
  ❌ 당근마켓/번개장터 등 실서비스 '스크래핑/크롤링/로그인 자동화/안티봇 우회'는 절대 하지 않는다.
  ❌ 실제 게시글 원문/이미지/사용자명/연락처/정확한 주소/계좌번호를 저장·표시하지 않는다.
  ✅ 올바른 제품 프레이밍: "실시장 트렌드를 '참고'한 가상의 NPC/매물 생성"
     (NOT "실제 게시글 복제").

어떤 제공자가 실패해도 synthetic 으로 안전하게 폴백한다 → 게임은 멈추지 않는다.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field, asdict

# source_type 상수
SOURCE_SYNTHETIC = "synthetic"
SOURCE_MANUAL = "manual_import"
SOURCE_TREND = "trend_cache"
SOURCE_OFFICIAL = "official_api"

ALLOWED_PROVIDERS = {"synthetic", "manual_import", "trend_cache", "official_stub"}


@dataclass
class MarketListingSeed:
    """
    정규화된 '매물 씨앗'. 완성된 NPC 도, 실제 게시글도 아니다.
    가상 시나리오 생성을 위한 '안전하고 비식별화된 시장 맥락'일 뿐이다.
    """
    source_type: str
    category: str
    product_name: str
    title_hint: str = ""
    price_hint: int | None = None
    market_price_hint: int | None = None
    condition_hint: str = ""
    common_defects: list[str] = field(default_factory=list)
    accessories: list[str] = field(default_factory=list)
    trade_methods: list[str] = field(default_factory=list)
    region_label: str = ""
    trend_tags: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)

    def to_hint(self) -> dict:
        """catalog.generate_listing(seed_hint=...) 에 넘길 dict."""
        return {
            "product_name": self.product_name,
            "title_hint": self.title_hint,
            "price_hint": self.price_hint,
            "market_price_hint": self.market_price_hint,
            "condition_hint": self.condition_hint,
            "common_defects": list(self.common_defects),
            "accessories": list(self.accessories),
            "trend_tags": list(self.trend_tags),
        }

    def to_dict(self) -> dict:
        return asdict(self)


class ListingProvider(abc.ABC):
    """매물 소스 인터페이스. 모든 제공자는 이걸 구현한다."""

    source_type: str = SOURCE_SYNTHETIC

    @abc.abstractmethod
    def fetch_listings(self, category: str, limit: int = 20) -> list[MarketListingSeed]:
        ...


# ============================================================
#  공식 API 스텁 (인터페이스만)
# ============================================================
class OfficialAPIProvider(ListingProvider):
    """
    공식 마켓 API 연동 자리표시자.

    ⚠️ 절대 규칙:
      - 공식 허가/계약/API 접근이 있을 때만 사용한다.
      - 스크래핑/크롤링/로그인 자동화/안티봇 우회/브라우저 자동화 금지.
      - 실제 게시글 원문/이미지/사용자명/연락처/정확한 주소를 게임에 그대로 노출 금지.

    이 스텁은 어떤 외부 호출도 하지 않는다. 항상 빈 목록을 돌려주어
    상위 팩토리가 synthetic 으로 폴백하게 한다.
    """

    source_type = SOURCE_OFFICIAL

    def fetch_listings(self, category: str, limit: int = 20) -> list[MarketListingSeed]:
        # TODO(공식 연동 시): 허가된 공식 API 만 사용. 응답은 normalizer 로 반드시 위생처리.
        #                    여기서 절대 임의의 외부 URL 을 요청하지 말 것.
        return []


# ============================================================
#  제공자 팩토리 (설정 기반 + 폴백)
# ============================================================
def _build_provider(name: str, settings):
    name = (name or "synthetic").lower()
    if name == "synthetic":
        from app.market.synthetic_provider import SyntheticListingProvider
        return SyntheticListingProvider()
    if name == "manual_import":
        from app.market.manual_import_provider import ManualImportProvider
        return ManualImportProvider(settings.market_import_path)
    if name == "trend_cache":
        from app.market.trend_cache import MarketTrendCacheProvider
        return MarketTrendCacheProvider(settings.market_trend_cache_path)
    if name == "official_stub":
        if not settings.allow_experimental_market_providers:
            return None  # 실험적 제공자 비활성 → synthetic 폴백
        return OfficialAPIProvider()
    return None


def get_listing_provider(settings=None) -> ListingProvider:
    """설정된 제공자를 만든다. 실패하면 synthetic 으로 폴백 (항상 동작 보장)."""
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    from app.market.synthetic_provider import SyntheticListingProvider

    name = (settings.market_listing_provider or "synthetic").lower()
    if name not in ALLOWED_PROVIDERS:
        name = "synthetic"
    try:
        provider = _build_provider(name, settings)
        if provider is None:
            return SyntheticListingProvider()
        return provider
    except Exception:
        # 어떤 이유로든 생성 실패 → 합성 제공자로 안전 폴백
        return SyntheticListingProvider()


def fetch_seeds(category: str, limit: int = 12, settings=None) -> list[MarketListingSeed]:
    """
    설정된 제공자로 seed 를 가져온다. 비거나 예외면 synthetic 으로 폴백.
    persona_factory 가 이 함수만 호출하면 된다.
    """
    from app.market.synthetic_provider import SyntheticListingProvider

    provider = get_listing_provider(settings)
    try:
        seeds = provider.fetch_listings(category, limit=limit)
    except Exception:
        seeds = []
    if not seeds and not isinstance(provider, SyntheticListingProvider):
        try:
            seeds = SyntheticListingProvider().fetch_listings(category, limit=limit)
        except Exception:
            seeds = []
    return seeds
