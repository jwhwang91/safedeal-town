"""
대략적 위치 추정 (IP 기반 + 좌표 역지오코딩).

목적: 마을 맵을 '사용자가 있는 곳' 근처 느낌으로 시드/이름 붙이기.
정밀 위치가 아니라 '도시/구' 수준의 대략값만 쓴다 (프라이버시).

설계 원칙 (이 앱의 일관된 규칙):
  - 키 없이 동작 (무료/무키 공개 서비스 사용).
  - 절대 멈추지 않는다: 모든 호출은 짧은 타임아웃 + 모든 예외 흡수 → 실패 시 None.
    (네트워크가 없거나 막혀도 게임은 절차적 맵으로 그냥 굴러간다.)
  - SSRF 방지: 외부로 보내는 IP/좌표는 먼저 검증한 값만 쓴다.
"""
from __future__ import annotations

import ipaddress

import httpx

_TIMEOUT = 2.5  # 초 — 실패해도 게임 흐름을 막지 않도록 짧게.
_MAX_LABEL = 40


def _clean_label(*parts: object) -> str | None:
    """장소명 조각들을 합쳐 사람이 읽을 짧은 라벨로. 비면 None."""
    seen: list[str] = []
    for p in parts:
        s = str(p or "").strip()
        if s and s.lower() not in ("none", "null") and s not in seen:
            seen.append(s)
    label = " ".join(seen).strip()
    if not label:
        return None
    return label[:_MAX_LABEL]


def public_client_ip(xff: str | None, peer: str | None) -> str | None:
    """
    역방향 프록시(X-Forwarded-For) 또는 직접 연결(peer) 중에서
    '공인(public) IP' 하나를 고른다. 사설/루프백/링크로컬은 무시한다.
    (로컬 개발에서는 보통 None 이 되어, 서버 자신의 공인 IP 로 폴백한다.)
    """
    candidates: list[str] = []
    if xff:
        candidates.extend(part.strip() for part in xff.split(","))
    if peer:
        candidates.append(peer.strip())
    for cand in candidates:
        if not cand:
            continue
        try:
            ip = ipaddress.ip_address(cand)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            continue
        # 스코프 ID(%)가 붙은 IPv6 는 URL 오염 우려가 있으니 제외.
        if "%" in str(ip):
            continue
        return str(ip)
    return None


def geolocate_ip(ip: str | None) -> dict | None:
    """
    IP → 대략 위치(도시 수준). ip 가 None 이면 서비스가 '요청자(=이 서버)의 공인 IP'
    로 추정한다 → 로컬 개발 시에도 개발자의 실제 도시 근처가 나온다.
    HTTPS 무키 서비스(ipwho.is)를 쓴다 (평문 HTTP 로 IP 가 새지 않도록).
    반환: {lat, lng, place_label, city, region, country} 또는 None.
    """
    # 들어온 IP 가 진짜 IP 인지 한 번 더 검증 (SSRF/오염 방지). 스코프 ID(%) 도 거른다.
    # 비정상이면 빈 문자열 → 서비스가 요청자(서버) IP 로 추정.
    safe_ip = ""
    if ip:
        try:
            addr = ipaddress.ip_address(ip)
            if "%" not in str(addr):
                safe_ip = str(addr)
        except ValueError:
            safe_ip = ""

    try:
        resp = httpx.get(f"https://ipwho.is/{safe_ip}", timeout=_TIMEOUT)
        data = resp.json()
    except Exception:
        return None

    if not isinstance(data, dict) or not data.get("success"):
        return None

    lat, lng = data.get("latitude"), data.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return None

    label = (
        _clean_label(data.get("city"))
        or _clean_label(data.get("region"))
        or _clean_label(data.get("country"))
    )
    return {
        "lat": float(lat),
        "lng": float(lng),
        "place_label": label,
        "city": data.get("city"),
        "region": data.get("region"),
        "country": data.get("country"),
    }


def reverse_geocode(lat: float | None, lng: float | None) -> dict | None:
    """
    브라우저 지오로케이션 좌표 → 대략 도시/구 이름. (무키: BigDataCloud)
    좌표는 호출 전에 이미 검증된 값(Pydantic ge/le)만 들어온다고 가정한다.
    실패하면 None (게임은 좌표 시드만으로 진행).
    """
    if lat is None or lng is None:
        return None
    url = "https://api.bigdatacloud.net/data/reverse-geocode-client"
    try:
        resp = httpx.get(
            url,
            params={
                "latitude": f"{float(lat):.4f}",
                "longitude": f"{float(lng):.4f}",
                "localityLanguage": "ko",
            },
            timeout=_TIMEOUT,
        )
        data = resp.json()
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    label = (
        _clean_label(data.get("locality"))
        or _clean_label(data.get("city"))
        or _clean_label(data.get("principalSubdivision"))
    )
    if not label:
        return None
    return {
        "place_label": label,
        "city": data.get("city") or data.get("locality"),
        "region": data.get("principalSubdivision"),
        "country": data.get("countryName"),
    }
