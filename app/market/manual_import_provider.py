"""
수동 import 매물 제공자.

개발자가 직접 둔 안전한 CSV/JSON 파일을 읽어 매물 씨앗으로 쓴다.
예) runtime/imports/market_listings.json  또는  .csv

매우 중요(안전/법적 경계):
  - 모든 행은 normalizer.normalize_row() 를 거쳐 '개인정보·식별정보'가 제거된다.
    (실제 사용자명/전화/이메일/정확한 주소/계좌번호/URL/이미지URL/긴 원문 → 전부 폐기)
  - 남기는 것은 상품명/카테고리/가격대/상태/구성품/하자 같은 비식별 메타데이터뿐.
  - 파일이 없거나 깨졌으면 빈 목록 → 상위 팩토리가 synthetic 으로 폴백한다.

이 제공자는 "내가 만든 안전한 샘플 데이터를 나중에 수동으로 넣기" 위한 통로다.
실제 마켓 스크래핑 결과를 그대로 넣는 용도가 아니다.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from app.market.normalizer import normalize_row
from app.market.providers import (
    SOURCE_MANUAL,
    ListingProvider,
    MarketListingSeed,
)


class ManualImportProvider(ListingProvider):
    source_type = SOURCE_MANUAL

    def __init__(self, import_path: str | Path) -> None:
        self.import_path = Path(import_path) if import_path else None

    # ---------- 파일 로드 ----------
    def _load_rows(self) -> list[dict]:
        p = self.import_path
        if not p or not p.exists():
            return []
        try:
            if p.suffix.lower() == ".csv":
                with p.open("r", encoding="utf-8-sig", newline="") as f:
                    return [dict(r) for r in csv.DictReader(f)]
            # 기본: JSON (리스트 또는 {"listings": [...]} )
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("listings") or data.get("items") or []
            return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError, csv.Error, UnicodeDecodeError):
            return []

    def fetch_listings(self, category: str, limit: int = 20) -> list[MarketListingSeed]:
        rows = self._load_rows()
        seeds: list[MarketListingSeed] = []
        want = (category or "random").lower()
        for row in rows:
            norm = normalize_row(row)  # ★ 위생처리: 개인정보 전부 제거
            if not norm:
                continue
            # 카테고리 필터 (random 이면 전부 허용)
            if want not in ("random", "", None) and norm["category"] not in (want, "random"):
                continue
            seeds.append(
                MarketListingSeed(
                    source_type=SOURCE_MANUAL,
                    category=norm["category"],
                    product_name=norm["product_name"],
                    title_hint=norm["title_hint"],
                    price_hint=norm["price_hint"],
                    market_price_hint=norm["market_price_hint"],
                    condition_hint=norm["condition_hint"],
                    common_defects=norm["common_defects"],
                    accessories=norm["accessories"],
                    trade_methods=norm["trade_methods"],
                    region_label=norm["region_label"],
                    trend_tags=norm["trend_tags"],
                    safety_notes=norm["safety_notes"],
                )
            )
            if len(seeds) >= max(1, limit):
                break
        return seeds
