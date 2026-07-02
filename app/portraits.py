"""
NPC 초상(얼굴) 이미지 리졸버 (백엔드 전용).

static/portraits/<family>/<gender>/<file>.png 구조의 실제 에셋을 읽어,
NPC 의 '정답지(role/tactics)' + 스폰 id(seed)로 결정적으로 얼굴 한 장을 고른다.

정답지 보호(핵심):
  - family 폴더명은 정상/사기 정체를 그대로 드러낸다(romance/refund_villain 등).
  - 따라서 이 모듈이 고른 '경로'는 서버에만 머문다. 프론트로는 스폰 id 만 담은
    불투명(opaque) URL 이 나가고(라우터 참고), family/role/gender 는 URL/헤더/파일명
    어디에도 실리지 않는다. (로맨스 사기꾼이 신뢰형 얼굴을 가질 수 있음 — 의도된 설계.)

결정성:
  - gender / file 선택은 seed(스폰 id) 해시로만 정해진다 → 같은 스폰은 항상 같은 얼굴.
  - hashlib 을 써서 프로세스 재시작에도 흔들리지 않는다(파이썬 hash() 는 문자열에 대해
    프로세스마다 달라짐).

견고성:
  - 디렉터리는 모듈 로드 시가 아니라 '첫 사용 시' 한 번 스캔해 캐시한다.
  - 폴더가 없거나 비어 있어도 절대 예외로 죽지 않는다 → 최종 폴백은 None.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# app/portraits.py → 프로젝트 루트/static/portraits (app/main.py 의 STATIC_DIR 방식 미러)
_ROOT = Path(__file__).resolve().parent.parent / "static" / "portraits"

_GENDERS = ("masculine", "feminine")
_DEFAULT_FAMILY = "default"

# 정상 판매자용 후보 폴더(다양성). seed 로 결정적으로 고른다. 기본은 honest_seller.
_HONEST_SELLER_FAMILIES = [
    "honest_seller", "professional_seller", "used_tech", "otaku", "rude_honest",
]

# {family: {gender: [정렬된 png 파일명, ...]}} — 첫 사용 시 한 번 스캔해 캐시.
_cache: dict[str, dict[str, list[str]]] | None = None


def _listing() -> dict[str, dict[str, list[str]]]:
    """static/portraits 실제 트리를 읽어 캐시(없거나 비면 빈 dict). 예외로 죽지 않음."""
    global _cache
    if _cache is not None:
        return _cache
    out: dict[str, dict[str, list[str]]] = {}
    try:
        if _ROOT.is_dir():
            for fam_dir in sorted(_ROOT.iterdir()):
                if not fam_dir.is_dir():
                    continue
                gmap: dict[str, list[str]] = {}
                for g in _GENDERS:
                    gdir = fam_dir / g
                    if not gdir.is_dir():
                        continue
                    files = sorted(
                        p.name for p in gdir.iterdir()
                        if p.is_file() and p.suffix.lower() == ".png"
                    )
                    if files:  # 빈 성별 폴더는 담지 않는다(폴백이 자연스럽게 걸리도록)
                        gmap[g] = files
                if gmap:
                    out[fam_dir.name] = gmap
    except OSError:
        out = {}
    _cache = out
    return out


def _seed_int(seed: str, salt: str) -> int:
    """seed(+salt) 로 프로세스 재시작에도 안정적인 정수 해시. 국면별 salt 로 독립 선택."""
    raw = f"{salt}|{seed or ''}".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest(), 16)


def _family_for(role: str, tactics: list[str] | None, seed: str) -> str:
    """NPC 의 내부 role(+tactics)을 가장 어울리는 초상 family 폴더로 매핑한다.

    ⚠️ 여기서 고른 family 는 정체를 드러낼 수 있으므로 절대 프론트로 나가면 안 된다.
    """
    role = (role or "").strip()
    tac = [str(t) for t in (tactics or [])]

    # ---- 구매자 NPC(판매자 모드) 역할 ----
    if role in ("honest_buyer", "legit_claim_buyer"):
        return "normal_buyer"
    if role == "refund_villain":
        # refund_villain 폴더가 비어 있으면 리졸버 폴백이 normal_buyer/default 로 넘긴다.
        return "refund_villain"
    if role == "private_contact_buyer":
        return "private_contact"
    if role == "romantic_pressure_buyer":
        return "romance"
    if role == "voice_phishing_buyer":
        return "voice_pressure"
    if role in ("social_engineering_buyer", "harasser_buyer", "risky_buyer",
                "ghosting_buyer", "lowballer"):
        return "suspicious_buyer"

    # ---- 판매자 NPC(구매자 모드): role 은 'honest' | 'scammer' ----
    if role == "scammer":
        # 수법에 따라 외형을 고르되, '평범한 사기꾼'은 신뢰형 얼굴로 위장한다
        # (일반 사기꾼이 시각적으로 튀어 정답이 새지 않도록).
        if any(("romantic" in t or "relationship" in t) for t in tac):
            return "romance"
        if any(("voice" in t or "phishing" in t or "phone" in t) for t in tac):
            return "voice_pressure"
        if any("private_contact" in t for t in tac):
            return "private_contact"
        return "honest_seller"  # 중립·신뢰형 (사기꾼이 겉으론 멀쩡)

    # honest 판매자(및 알 수 없는 role 폴백): 다양성 있게 seed 로 고른다.
    idx = _seed_int(seed, "family") % len(_HONEST_SELLER_FAMILIES)
    return _HONEST_SELLER_FAMILIES[idx]


def _gender_order(seed: str) -> list[str]:
    """seed 해시로 성별을 결정적으로 정하고, 폴백용으로 반대 성별을 뒤에 붙인다."""
    primary = "masculine" if (_seed_int(seed, "gender") % 2 == 0) else "feminine"
    other = "feminine" if primary == "masculine" else "masculine"
    return [primary, other]


def resolve_portrait_path(role: str | None, tactics: list[str] | None,
                          seed: str | None) -> Path | None:
    """role(+tactics) + seed(스폰 id) → 초상 이미지 절대 경로. 없으면 None(절대 예외 없음).

    폴백 체인: (선택 family)/기본성별 → (선택 family)/반대성별
             → default/기본성별 → default/반대성별 → None.
    파일은 seed 해시 % 파일수 로 결정 → 같은 스폰은 항상 같은 얼굴.
    """
    listing = _listing()
    if not listing:
        return None
    seed = seed or ""
    family = _family_for(role or "", tactics, seed)
    genders = _gender_order(seed)

    # 선택 family → default family 순으로, 각 family 안에서 (기본성별 → 반대성별) 탐색.
    for fam in (family, _DEFAULT_FAMILY):
        fam_map = listing.get(fam)
        if not fam_map:
            continue
        for g in genders:
            files = fam_map.get(g)
            if files:
                idx = _seed_int(seed, "file") % len(files)
                return _ROOT / fam / g / files[idx]
    return None
