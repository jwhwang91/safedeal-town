"""
커뮤니티 제출물 모더레이션 (사례/댓글).

목표(데모 수준, 규칙 기반):
  - 과도한 개인정보가 섞인 글은 자동 승인하지 않고 'pending'(검토 대기)으로 돌린다.
  - 노골적 혐오/폭력/괴롭힘/신상털기(doxxing) 유도는 거부(reject)한다.
  - 사용자에게 제출 전 경고 문구를 노출한다.

이 모듈은 '정답 라벨'을 정하지 않는다. 안전 게이트일 뿐이며, 실패 시에도 앱은 계속 동작한다.
LLM 을 쓰지 않는다(규칙 기반). 오탐이 있어도 '거부보다 pending' 쪽으로 보수적으로 판단한다.
"""
from __future__ import annotations

import re

from app.privacy.redactor import count_sensitive_hits

# 제출 전 사용자에게 보여줄 안내 (프론트가 그대로 노출)
SUBMIT_NOTICE = (
    "개인정보는 자동으로 가려지지만, 실명·계좌번호·연락처는 직접 적지 않는 것을 권장합니다. "
    "이 곳의 사례는 비식별 처리 후 방어 훈련 자료로만 쓰여요."
)

# 노골적 혐오/폭력/신상털기 유도 — 거부. (데모용 최소 사전; 과도하게 넓히지 않는다)
_REJECT_PATTERNS = [
    re.compile(r"(신상\s?털|신상\s?공개|주소\s?좀\s?알려|집\s?주소\s?찾)", re.IGNORECASE),
    re.compile(r"(죽여|죽이겠|찾아가서\s?패|칼\s?들고|폭행하)", re.IGNORECASE),
    re.compile(r"(좌표\s?찍|이\s?새끼\s?어디\s?사|찾아내서\s?복수)", re.IGNORECASE),
]

# 과도한 개인정보 임계값: 원문에서 민감정보 히트가 이 이상이면 pending 으로.
_SENSITIVE_PENDING_THRESHOLD = 4

_MAX_BODY_CHARS = 4000


def check_submission(text: str) -> dict:
    """사례/댓글 원문을 검사해 처리 방침을 돌려준다.

    반환:
      {
        "action": "accept" | "pending" | "reject",
        "reasons": ["..."],           # 사용자/로그용 사유 (한국어)
        "sensitive_hits": int,        # 원문에서 발견된 민감정보 대략 건수
      }
    """
    s = str(text or "")
    reasons: list[str] = []

    if len(s.strip()) == 0:
        return {"action": "reject", "reasons": ["내용이 비어 있어요."], "sensitive_hits": 0}
    if len(s) > _MAX_BODY_CHARS:
        reasons.append("내용이 너무 길어요. 핵심만 간단히 적어 주세요.")

    for pat in _REJECT_PATTERNS:
        if pat.search(s):
            return {
                "action": "reject",
                "reasons": ["신상 공개·폭력·괴롭힘을 유도하는 내용은 올릴 수 없어요."],
                "sensitive_hits": count_sensitive_hits(s),
            }

    hits = count_sensitive_hits(s)
    if hits >= _SENSITIVE_PENDING_THRESHOLD:
        reasons.append(
            "개인정보로 보이는 내용이 많아 자동 공개 대신 검토 대기로 접수했어요. "
            "(연락처·계좌·실명은 빼고 다시 적어 주시면 좋아요.)"
        )
        return {"action": "pending", "reasons": reasons, "sensitive_hits": hits}

    action = "accept" if not reasons else "pending"
    return {"action": action, "reasons": reasons, "sensitive_hits": hits}
