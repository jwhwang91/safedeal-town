#!/usr/bin/env python3
"""
초상(NPC 얼굴) 매니페스트 빌더 — 스포일러 없는 공개 태깅.

무엇을 하나:
  static/portraits/<family>/<gender>/*.jpg 트리를 훑어서,
  각 이미지에 '공개 아키타입(비-스포일러)' + gender_presentation + (백엔드 전용) 숨은
  eligible 페르소나 family 태그를 붙인 매니페스트를 만든다:
      static/portraits/portraits_manifest.json

왜 이렇게 하나 (정답지 보호):
  - 물리 폴더명(romance / refund_villain …)은 정답(정상/사기 정체)을 그대로 드러낸다.
  - 그래서 '폴더명'은 매칭 신호로 직접 쓰지 않는다. 대신 폴더 → '공개 아키타입'
    (warm_social / professional / ordinary / hobby / assertive / neutral)으로 뭉갠다.
  - 하나의 아키타입은 '정상'과 '위험' 페르소나가 함께 쓸 수 있게 설계된다
    (따뜻한 얼굴 == 로맨스 사기 가 아니게). 그래서 얼굴만 보고 정답을 못 맞힌다.
  - eligible_persona_families_internal 은 '약한 가점(tie-breaker)'용 백엔드 전용 태그다.
    프론트로는 절대 나가지 않는다 (app/portraits.py 가 공개 payload 에서 뺀다).

기본 동작:
  - 이미지를 옮기지 않는다. 매니페스트의 path 는 실제 서버 경로를 가리킨다.
    (프론트는 이 경로를 절대 못 본다 — /api/chat/portrait/{spawn_id} 불투명 URL 로만 서빙.)

--public-copies (옵션):
  - static/assets/portraits/public/p_0001.jpg … 로 '완전 불투명 파일명'을 만들고
    매니페스트 path 를 그 공개 경로로 바꾼다 (물리 파일명까지 스포일러 제거하고 싶을 때).
  - 원본은 그대로 두고 복사만 한다.

사용:
  python scripts/build_portrait_public_assets.py            # 매니페스트만 (이미지 유지)
  python scripts/build_portrait_public_assets.py --public-copies
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "static" / "portraits"
MANIFEST_PATH = SRC_DIR / "portraits_manifest.json"
PUBLIC_DIR = ROOT / "static" / "assets" / "portraits" / "public"

# 얼굴별 '중립 외형 속성'(나이대/옷차림/액세서리/머리) 사이드카.
#   - 각 이미지를 실제로 보고 태깅한 값이며 소스 상대경로(<family>/<gender>/<file>)로 키한다.
#   - 여기 담긴 속성으로 페르소나 겉모습 설명을 '실제 얼굴에 맞춰' 생성한다(app/ai/persona_identity.py).
#   - ⚠️ 나이/옷차림/액세서리처럼 role(정상/사기)과 무관한 중립 정보만 담는다(정답 비노출).
#   - 폴더 리빌드(asset_id 재번호)에도 살아남도록 매니페스트와 '분리'해 둔다.
ATTRS_PATH = SRC_DIR / "portrait_attributes.json"
_ATTR_KEYS = ("age_band", "attire", "accessories", "hair")

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_GENDERS = ("feminine", "masculine", "neutral")

# ---------------------------------------------------------------
#  폴더(정답 힌트) → 공개 아키타입(비-스포일러). 여러 폴더가 한 아키타입으로 뭉쳐서
#  '얼굴만으로 정체 추리'가 안 되게 만든다.
# ---------------------------------------------------------------
FOLDER_ARCHETYPE = {
    "romance": "warm_social",
    "private_contact": "warm_social",
    "normal_buyer": "ordinary",
    "honest_seller": "ordinary",
    "used_tech": "ordinary",
    "suspicious_buyer": "ordinary",     # '수상한' 얼굴을 평범 풀에 섞어 스포일러 제거
    "professional_seller": "professional",
    "voice_pressure": "professional",
    "otaku": "hobby",
    "rude_honest": "assertive",
    "refund_villain": "assertive",
    "default": "neutral",
}

# 공개 vibe(중립 단어만). 스포일러 라벨(scam/romance/villain 등) 금지.
FOLDER_VIBE = {
    "romance": ["friendly", "soft", "warm"],
    "private_contact": ["friendly", "chatty"],
    "normal_buyer": ["ordinary", "casual"],
    "honest_seller": ["ordinary", "calm"],
    "used_tech": ["casual", "practical"],
    "suspicious_buyer": ["reserved", "cautious"],
    "professional_seller": ["professional", "polished"],
    "voice_pressure": ["professional", "earnest"],
    "otaku": ["hobby", "enthusiast"],
    "rude_honest": ["blunt", "direct"],
    "refund_villain": ["assertive", "insistent"],
    "default": ["neutral"],
}

# 상품 카테고리 맥락(약한 가점용). 없으면 [].
FOLDER_CONTEXT_CATEGORIES = {
    "otaku": ["game", "hobby", "book", "figure", "comic", "anime"],
    "used_tech": ["electronics", "phone", "laptop", "digital", "tablet"],
}

# 백엔드 전용: 이 얼굴을 '자연스럽게' 쓸 수 있는 숨은 family 들 (정상+위험 섞음 → 약한 신호).
# ⚠️ 프론트로 절대 내보내지 않는다.
FOLDER_ELIGIBLE_INTERNAL = {
    "romance": ["romance", "private_contact", "normal_buyer", "honest_seller"],
    "private_contact": ["private_contact", "romance", "normal_buyer", "honest_seller"],
    "normal_buyer": ["normal_buyer", "honest_seller", "suspicious_buyer"],
    "honest_seller": ["honest_seller", "normal_buyer", "voice_pressure"],
    "used_tech": ["honest_seller", "normal_buyer", "suspicious_buyer"],
    "suspicious_buyer": ["suspicious_buyer", "normal_buyer", "honest_seller"],
    "professional_seller": ["honest_seller", "voice_pressure", "normal_buyer"],
    "voice_pressure": ["voice_pressure", "honest_seller", "normal_buyer"],
    "otaku": ["normal_buyer", "honest_seller", "private_contact", "suspicious_buyer"],
    "rude_honest": ["honest_seller", "refund_villain", "suspicious_buyer"],
    "refund_villain": ["refund_villain", "suspicious_buyer", "honest_seller", "normal_buyer"],
    "default": ["default"],
}


def _iter_images() -> list[tuple[str, str, Path]]:
    """(family, gender, path) 목록을 결정적 순서로 반환."""
    items: list[tuple[str, str, Path]] = []
    if not SRC_DIR.is_dir():
        return items
    for fam_dir in sorted(SRC_DIR.iterdir()):
        if not fam_dir.is_dir():
            continue
        family = fam_dir.name
        for gender in _GENDERS:
            gdir = fam_dir / gender
            if not gdir.is_dir():
                continue
            for f in sorted(gdir.iterdir()):
                if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
                    items.append((family, gender, f))
    return items


def _load_attributes() -> dict[str, dict]:
    """중립 외형 속성 사이드카 로드 (없으면 빈 dict — 속성 없이도 매니페스트는 만들어진다)."""
    try:
        if ATTRS_PATH.is_file():
            data = json.loads(ATTRS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def build(public_copies: bool) -> list[dict]:
    images = _iter_images()
    attrs = _load_attributes()
    if public_copies:
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        # 소스 이미지 세트가 바뀌면 p_XXXX 번호가 밀리므로, 이전 복사본을 먼저 지운다
        # (고아 파일 누적 방지). p_* 만 지워 다른 파일은 건드리지 않는다.
        for old in PUBLIC_DIR.glob("p_*"):
            if old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass

    manifest: list[dict] = []
    for i, (family, gender, path) in enumerate(images, start=1):
        asset_id = f"p_{i:04d}"
        archetype = FOLDER_ARCHETYPE.get(family, "neutral")

        if public_copies:
            dst = PUBLIC_DIR / f"{asset_id}{path.suffix.lower()}"
            shutil.copy2(path, dst)
            public_path = f"/static/assets/portraits/public/{dst.name}"
        else:
            # 원본 위치를 그대로 가리킨다 (프론트는 이 경로를 못 본다).
            rel = path.relative_to(ROOT / "static").as_posix()
            public_path = f"/static/{rel}"

        entry = {
            "asset_id": asset_id,
            "path": public_path,
            "gender_presentation": gender,
            "public_archetype": archetype,
            "vibe": FOLDER_VIBE.get(family, ["neutral"]),
            "context_categories": FOLDER_CONTEXT_CATEGORIES.get(family, []),
            # --- 백엔드 전용 (프론트 미노출) ---
            "eligible_persona_families_internal": FOLDER_ELIGIBLE_INTERNAL.get(
                family, ["default"]
            ),
        }
        # 중립 외형 속성 병합 (소스 상대경로로 매칭). 사이드카에 없으면 속성 없이 둔다.
        rel_key = f"{family}/{gender}/{path.name}"
        tagged = attrs.get(rel_key)
        if isinstance(tagged, dict):
            for k in _ATTR_KEYS:
                if k in tagged:
                    entry[k] = tagged[k]
        manifest.append(entry)
    return manifest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="초상 매니페스트 빌더 (스포일러 없는 공개 태깅)")
    ap.add_argument(
        "--public-copies", action="store_true",
        help="static/assets/portraits/public/p_XXXX 로 불투명 파일명 복사본 생성",
    )
    args = ap.parse_args(argv)

    manifest = build(args.public_copies)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 요약 (스포일러 없는 통계만)
    by_arch: dict[str, int] = {}
    by_gender: dict[str, int] = {}
    for e in manifest:
        by_arch[e["public_archetype"]] = by_arch.get(e["public_archetype"], 0) + 1
        by_gender[e["gender_presentation"]] = by_gender.get(e["gender_presentation"], 0) + 1

    print(f"[build_portrait_public_assets] {len(manifest)} images -> {MANIFEST_PATH}")
    print(f"  by public_archetype: {dict(sorted(by_arch.items()))}")
    print(f"  by gender:           {dict(sorted(by_gender.items()))}")
    if args.public_copies:
        print(f"  opaque copies:       {PUBLIC_DIR}")
    else:
        print("  mode: manifest points at original server paths (no image copies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
