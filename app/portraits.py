"""
NPC 초상(얼굴) 이미지 리졸버 (백엔드 전용).

NPC 의 '정답지(role/tactics)' + 겉모습(gender_presentation/카테고리) + 스폰 id(seed)로
결정적으로 얼굴 한 장을 고른다. 두 가지 소스를 지원한다:

  1) 매니페스트 모드(우선): static/portraits/portraits_manifest.json
     - 각 이미지에 '공개 아키타입(비-스포일러)' + gender + (백엔드 전용) 숨은 eligible family
       태그가 붙어 있다 (scripts/build_portrait_public_assets.py 가 생성).
     - 정답 보호의 핵심: '공개 아키타입'은 정상/위험 페르소나가 함께 쓴다 → 얼굴만 보고
       정답을 못 맞힌다. 숨은 family 는 '약한 tie-breaker'로만 쓴다(지배 신호 금지).
  2) 폴더 스캔 폴백: 매니페스트가 없으면 static/portraits/<family>/<gender>/ 를 직접 스캔.

정답지 보호(핵심):
  - 이 모듈이 고른 '경로/아키타입/family'는 전부 서버에만 머문다.
    프론트로는 스폰 id 만 담은 불투명(opaque) URL 이 나가고(chat 라우터 참고),
    family/role/gender/archetype/파일명 어디에도 정답이 실리지 않는다.
    (로맨스 사기꾼이 신뢰형 얼굴을 가질 수 있음 — 의도된 설계.)

결정성:
  - gender / 파일 선택은 seed(스폰 id) 해시로만 정해진다 → 같은 스폰은 항상 같은 얼굴.
  - hashlib 을 써서 프로세스 재시작에도 흔들리지 않는다(파이썬 hash() 는 프로세스마다 달라짐).

견고성:
  - 매니페스트/디렉터리는 '첫 사용 시' 한 번 읽어 캐시한다.
  - 파일이 없거나 비어 있어도 절대 예외로 죽지 않는다 → 최종 폴백은 None(프론트 절차적 폴백).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# app/portraits.py → 프로젝트 루트/static (app/main.py 의 STATIC_DIR 방식 미러)
_STATIC = Path(__file__).resolve().parent.parent / "static"
_ROOT = _STATIC / "portraits"
_MANIFEST_PATH = _ROOT / "portraits_manifest.json"

_GENDERS = ("masculine", "feminine")
_DEFAULT_FAMILY = "default"

# 지원 이미지 확장자(포맷 무관). 초상은 웹 최적화를 위해 jpg 로 내려갈 수 있다.
_IMAGE_EXTS = (".webp", ".jpg", ".jpeg", ".png")

# gender_presentation 허용값. '생물학적 성별' 개념이 아니라 '가상 프로필 외형' 매칭용.
_GENDER_ALLOWED = ("feminine", "masculine", "neutral", "unknown")


# ---------------------------------------------------------------
#  role(+tactics) → 내부 family (정답 힌트). ⚠️ 서버 전용, 프론트 미노출.
# ---------------------------------------------------------------
def _internal_family(role: str, tactics: list[str] | None) -> str:
    role = (role or "").strip()
    tac = [str(t) for t in (tactics or [])]

    # ---- 구매자 NPC(판매자 모드) 역할 ----
    if role in ("honest_buyer", "legit_claim_buyer"):
        return "normal_buyer"
    if role == "refund_villain":
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
        if any(("romantic" in t or "relationship" in t) for t in tac):
            return "romance"
        if any(("voice" in t or "phishing" in t or "phone" in t) for t in tac):
            return "voice_pressure"
        if any("private_contact" in t for t in tac):
            return "private_contact"
        # '평범한 사기꾼'은 신뢰형(정상 판매자와 같은 풀)으로 위장한다.
        return "honest_seller"

    # honest 판매자 및 알 수 없는 role
    if role == "honest":
        return "honest_seller"
    return _DEFAULT_FAMILY


# ---------------------------------------------------------------
#  내부 family → 공개 아키타입 가중치.
#  같은 아키타입을 '정상'과 '위험' family 가 함께 쓰도록 설계 → 얼굴로 정답 못 맞힘.
#  (첫 항목이 primary(가장 높은 가중치). 가중치는 '후보 풀 내 배수'로 쓰인다.)
# ---------------------------------------------------------------
_FAMILY_ARCHETYPES: dict[str, list[tuple[str, int]]] = {
    "romance":          [("warm_social", 3), ("ordinary", 2), ("hobby", 1), ("neutral", 1)],
    "private_contact":  [("warm_social", 3), ("hobby", 2), ("ordinary", 1), ("neutral", 1)],
    "voice_pressure":   [("professional", 3), ("ordinary", 2), ("neutral", 1)],
    "refund_villain":   [("assertive", 3), ("ordinary", 2), ("neutral", 1)],
    "suspicious_buyer": [("ordinary", 3), ("assertive", 2), ("hobby", 1), ("neutral", 1)],
    "honest_seller":    [("ordinary", 3), ("warm_social", 2), ("professional", 2),
                         ("assertive", 1), ("hobby", 1), ("neutral", 1)],
    "normal_buyer":     [("ordinary", 3), ("warm_social", 2), ("hobby", 2),
                         ("assertive", 1), ("professional", 1), ("neutral", 1)],
    _DEFAULT_FAMILY:    [("ordinary", 2), ("warm_social", 2), ("professional", 1),
                         ("hobby", 1), ("assertive", 1), ("neutral", 1)],
}

# None = 아직 안 읽음. [] = 매니페스트가 없거나 비었음.
_manifest: list[dict] | None = None
# {family: {gender: [파일명…]}} — 폴더 스캔 폴백 캐시.
_folder_cache: dict[str, dict[str, list[str]]] | None = None


# ============================================================
#  공용 유틸
# ============================================================
def normalize_gender_presentation(value, text_hint: str | None = None) -> str:
    """gender_presentation 을 허용 enum 으로 정규화. 잘못됐거나 없으면 텍스트에서 추론, 그래도 애매하면 'unknown'.

    '생물학적 성별'이 아니라 '가상 프로필 외형' 매칭용 라벨이다. 실제 신원 추론 금지.
    """
    v = str(value or "").strip().lower()
    if v in _GENDER_ALLOWED:
        return v
    # 흔한 동의어 매핑
    alias = {
        "female": "feminine", "woman": "feminine", "women": "feminine", "f": "feminine",
        "여": "feminine", "여성": "feminine",
        "male": "masculine", "man": "masculine", "men": "masculine", "m": "masculine",
        "남": "masculine", "남성": "masculine",
        "androgynous": "neutral", "nonbinary": "neutral", "ambiguous": "neutral",
    }
    if v in alias:
        return alias[v]
    # 공개 텍스트에서 '명백할 때만' 안전하게 추론 (아니면 unknown).
    # 영어는 단어 경계(\b)로 매칭 → 'male'⊄'female', 'man'⊄'woman'/'human' 오탐 방지.
    # 한국어 토큰은 부분문자열이라도 상호 오탐이 없어(여성/여자 ↔ 남성/남자) 그대로 검사.
    t = str(text_hint or "")
    tl = t.lower()
    fem = bool(re.search(r"\b(woman|women|female|she|her|girl|lady)\b", tl)) \
        or any(k in t for k in ("여성", "여자", "그녀"))
    mas = bool(re.search(r"\b(man|men|male|he|his|guy|boy)\b", tl)) \
        or any(k in t for k in ("남성", "남자"))
    if fem and not mas:
        return "feminine"
    if mas and not fem:
        return "masculine"
    return "unknown"


def _seed_int(seed: str, salt: str) -> int:
    """seed(+salt) 로 프로세스 재시작에도 안정적인 정수 해시. 국면별 salt 로 독립 선택."""
    raw = f"{salt}|{seed or ''}".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest(), 16)


# ============================================================
#  매니페스트 로딩/선택
# ============================================================
def _load_manifest() -> list[dict]:
    global _manifest
    if _manifest is not None:
        return _manifest
    out: list[dict] = []
    try:
        if _MANIFEST_PATH.is_file():
            data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for e in data:
                    if isinstance(e, dict) and e.get("path"):
                        out.append(e)
    except (OSError, json.JSONDecodeError, TypeError):
        out = []
    _manifest = out
    return out


def _fs_path(public_path: str) -> Path | None:
    """매니페스트의 공개 경로(/static/...) → 실제 파일시스템 경로. 벗어나면 None(경로 이탈 방지)."""
    p = str(public_path or "")
    if not p.startswith("/static/"):
        return None
    rel = p[len("/static/"):]
    try:
        fs = (_STATIC / rel).resolve()
        fs.relative_to(_STATIC.resolve())  # 디렉터리 이탈 방지
    except (ValueError, OSError):
        return None
    return fs


def _entry_weight(entry: dict, family: str, category: str | None) -> int:
    """이 이미지가 이 NPC 후보 풀에 들어갈 배수(0=제외). 아키타입이 지배 신호, 나머지는 약한 가점."""
    arch = entry.get("public_archetype", "neutral")
    weights = dict(_FAMILY_ARCHETYPES.get(family, _FAMILY_ARCHETYPES[_DEFAULT_FAMILY]))
    base = weights.get(arch, 0)
    if base <= 0:
        return 0  # 이 family 가 쓰지 않는 아키타입 → 후보 제외
    bonus = 0
    # 상품 카테고리 맥락 (약한 가점)
    if category:
        cat = category.lower()
        cats = entry.get("context_categories") or []
        if any(str(c).lower() in cat or cat in str(c).lower() for c in cats):
            bonus += 1
    # 숨은 family eligibility (아주 약한 tie-breaker — 지배 금지)
    elig = entry.get("eligible_persona_families_internal") or []
    if family in elig:
        bonus += 1
    return base + bonus


def _pick_from_manifest(manifest: list[dict], family: str, gender: str,
                        category: str | None, seed: str) -> dict | None:
    """gender 우선 → 가중 후보 풀 → seed 해시로 결정적 선택. 고른 '매니페스트 엔트리'를 돌려준다.

    gender 우선순위: 요청 gender → neutral → 전체 (매칭 폴더가 비면 자연스럽게 넘어감).
    같은 seed 는 항상 같은 얼굴, 다른 NPC 는 (정상/위험 무관) 같은 아키타입 풀을 공유한다.
    반환한 엔트리의 파일이 실제로 존재함을 보장한다(없으면 다음 gender 군으로 폴백, 최종 None).
    """
    if gender == "feminine":
        gender_orders = [("feminine",), ("neutral",), ("feminine", "masculine", "neutral")]
    elif gender == "masculine":
        gender_orders = [("masculine",), ("neutral",), ("masculine", "feminine", "neutral")]
    elif gender == "neutral":
        gender_orders = [("neutral",), ("feminine", "masculine", "neutral")]
    else:  # unknown → seed 로 성별 하나 정하고, 안 되면 전체
        first = "feminine" if (_seed_int(seed, "gender") % 2 == 0) else "masculine"
        second = "masculine" if first == "feminine" else "feminine"
        gender_orders = [(first,), (second,), ("neutral",),
                         ("feminine", "masculine", "neutral")]

    for genders in gender_orders:
        # (asset_id, weight, entry) 로 결정적 정렬된 가중 후보 풀을 만든다.
        pool: list[tuple[str, int, dict]] = []
        for e in manifest:
            if e.get("gender_presentation") not in genders:
                continue
            w = _entry_weight(e, family, category)
            if w > 0:
                pool.append((str(e.get("asset_id") or e.get("path")), w, e))
        if not pool:
            continue
        pool.sort(key=lambda x: x[0])  # asset_id 로 결정적 순서

        # 가중치를 배수로 펼쳐 '누적 가중 선택' → primary 아키타입이 더 자주,
        # secondary 도 가끔 (스테레오타입 고정 방지 + 정상/위험 풀 겹침 보장).
        total = sum(w for _, w, _ in pool)
        target = _seed_int(seed, "portrait") % total
        acc = 0
        for _, w, entry in pool:
            acc += w
            if target < acc:
                fs = _fs_path(entry.get("path"))
                if fs and fs.is_file():
                    return entry
                break  # 고른 파일이 사라졌으면 이 gender 군은 포기하고 다음으로
    return None


# ============================================================
#  폴더 스캔 폴백 (매니페스트가 없을 때)
# ============================================================
def _folder_listing() -> dict[str, dict[str, list[str]]]:
    global _folder_cache
    if _folder_cache is not None:
        return _folder_cache
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
                        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
                    )
                    if files:
                        gmap[g] = files
                if gmap:
                    out[fam_dir.name] = gmap
    except OSError:
        out = {}
    _folder_cache = out
    return out


def _folder_family_for(role: str, tactics: list[str] | None, seed: str) -> str:
    """폴더 폴백용 family. honest 판매자는 여러 폴더로 분산(다양성)."""
    fam = _internal_family(role, tactics)
    if fam == "honest_seller":
        pool = ["honest_seller", "professional_seller", "used_tech", "otaku", "rude_honest"]
        return pool[_seed_int(seed, "family") % len(pool)]
    return fam


def _gender_order(gender: str, seed: str) -> list[str]:
    """폴더 폴백용 성별 순서: 요청 gender 우선, 없으면 seed 로."""
    if gender == "feminine":
        return ["feminine", "masculine"]
    if gender == "masculine":
        return ["masculine", "feminine"]
    primary = "masculine" if (_seed_int(seed, "gender") % 2 == 0) else "feminine"
    other = "feminine" if primary == "masculine" else "masculine"
    return [primary, other]


def _pick_from_folders(family: str, gender: str, seed: str) -> Path | None:
    listing = _folder_listing()
    if not listing:
        return None
    genders = _gender_order(gender, seed)
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


# ============================================================
#  공개 진입점
# ============================================================
def resolve_portrait_entry(role: str | None, tactics: list[str] | None,
                           seed: str | None,
                           gender_presentation: str | None = None,
                           category: str | None = None) -> dict | None:
    """role(+tactics)+gender+category+seed → 선택된 '매니페스트 엔트리'(외형 속성 포함) 또는 None.

    엔트리에는 asset_id/path/gender_presentation 과, 매니페스트에 병합된 외형 속성
    (age_band/attire/accessories/hair)이 담긴다. 이 속성으로 페르소나의 겉모습 설명을
    '실제 얼굴에 맞춰' 생성한다. 매니페스트가 없으면(=폴더 폴백 상황) None 을 돌려준다.

    ⚠️ 정답지 보호: 여기서 쓰는 속성은 age/attire/accessories 처럼 '역할과 무관한' 중립
    외형 정보뿐이다. archetype/vibe/family 같은 상관 신호는 공개 설명에 절대 넣지 않는다.
    """
    seed = seed or ""
    gender = normalize_gender_presentation(gender_presentation)
    family = _internal_family(role or "", tactics)
    manifest = _load_manifest()
    if not manifest:
        return None
    entry = _pick_from_manifest(manifest, family, gender, category, seed)
    if entry is None:
        return None
    fs = _fs_path(entry.get("path"))
    if not (fs and fs.is_file()):
        return None
    out = dict(entry)
    out["fs_path"] = str(fs)
    return out


def path_for_asset_id(asset_id: str | None) -> Path | None:
    """매니페스트 asset_id → 실제 파일 경로. 스폰에 '고정된' 초상을 정확히 그대로 서빙할 때 쓴다.

    생성 시 고른 얼굴의 asset_id 를 dynamic_json 에 박아두면, 서빙 때 재-리졸브(매니페스트
    가중치 변동 등)로 다른 얼굴이 나오는 일 없이 항상 같은 얼굴을 돌려준다. 없으면 None.
    """
    if not asset_id:
        return None
    for e in _load_manifest():
        if e.get("asset_id") == asset_id:
            fs = _fs_path(e.get("path"))
            return fs if (fs and fs.is_file()) else None
    return None


def resolve_portrait_path(role: str | None, tactics: list[str] | None,
                          seed: str | None,
                          gender_presentation: str | None = None,
                          category: str | None = None) -> Path | None:
    """role(+tactics) + gender + category + seed(스폰 id) → 초상 파일 절대경로. 없으면 None(예외 없음).

    우선 매니페스트(스코어링·gender·가중 top-N)로, 없으면 폴더 스캔으로 폴백한다.
    같은 스폰 id 는 항상 같은 얼굴을 돌려준다.
    """
    seed = seed or ""
    gender = normalize_gender_presentation(gender_presentation)
    family = _internal_family(role or "", tactics)

    manifest = _load_manifest()
    if manifest:
        entry = _pick_from_manifest(manifest, family, gender, category, seed)
        if entry is not None:
            fs = _fs_path(entry.get("path"))
            if fs and fs.is_file():
                return fs
        # 매니페스트로 못 골랐으면(파일 소실 등) 폴더 폴백도 시도.

    fam = _folder_family_for(role or "", tactics, seed)
    return _pick_from_folders(fam, gender, seed)
