"""
이미지 생성 클라이언트 (OpenAI Images API).

'실물 인증사진'이 필요한 미션(proof_first_buyer)에서, 그리고 이미지 생성이 가능한
배포 환경(Settings.photo_generation_available — 현재는 openai 모드)에서만 호출된다.
실패(키 없음/네트워크 오류/타임아웃/거부 등)는 절대 게임을 막지 않는다 — 호출부는
None 을 받으면 사진 없이 텍스트만으로 그대로 진행한다.

안전: 실제 사람 얼굴·신분증/서류·화폐·바코드/QR·읽을 수 있는 브랜드 로고나 일련번호처럼
'진짜로 도용될 수 있는' 요소는 프롬프트에서 명시적으로 금지한다. 이 함수는 오직
"플레이어가 이미 요청한, 이번 세션 한정 인증사진 한 장"만 만든다 — 대량 생성이나
플레이어가 원하는 임의의 프롬프트를 그대로 받는 용도가 아니다.
"""
from __future__ import annotations

import base64
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_SAFETY_SUFFIX = (
    " Plain simple product photo style, neutral background, soft daylight. "
    "Do NOT include any real-looking human faces, ID cards or official documents, "
    "currency or coins, barcodes or QR codes, or readable real brand logos/serial numbers. "
    "The date note should show only a generic handwritten date, not any real personal data. "
    "This is fictional training-simulator content, not a real marketplace listing."
)


def generate_proof_photo(item_name: str, item_category: str) -> str | None:
    """중고거래 인증사진(실물 사진 + 오늘 날짜 메모)을 생성해 data URI 로 돌려준다.

    반환값은 "data:image/png;base64,<...>" 형태이거나, 실패 시 None.
    """
    settings = get_settings()
    if not settings.photo_generation_available:
        return None

    prompt = (
        f'A secondhand-marketplace verification photo of a "{item_name}" '
        f"({item_category}) item, placed next to a small handwritten paper note "
        "showing today's date, proving the seller currently has the item in hand."
        + _SAFETY_SUFFIX
    )
    url = f"{settings.openai_base_url.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openai_image_model,
        "prompt": prompt,
        "size": "1024x1024",
        "n": 1,
    }

    try:
        with httpx.Client(timeout=settings.openai_image_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        item = data["data"][0]
        b64 = item.get("b64_json")
        if not b64 and item.get("url"):
            # gpt-image-1 은 항상 b64_json 을 주지만, dall-e-3 등 일부 모델/설정은 url 을 줄 수 있다.
            with httpx.Client(timeout=settings.openai_image_timeout_seconds) as client:
                img_resp = client.get(item["url"])
                img_resp.raise_for_status()
            b64 = base64.b64encode(img_resp.content).decode("ascii")
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        logger.warning("인증사진 생성 실패, 텍스트만으로 진행: %s", exc)
        return None

    if not b64:
        return None
    return f"data:image/png;base64,{b64}"
