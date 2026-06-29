"""
AI 출력 위생 처리 (sanitize).

LLM(또는 로컬 CLI)이 뱉은 문자열을 화면/DB 에 넣기 전에 한 번 거른다:
  - 문자열 강제 + 양끝 공백 제거
  - 제어문자 제거
  - 과도한 줄바꿈/공백 축소
  - 길이 제한 (채팅 한 마디로는 충분, 폭주 방어)

정답(role/tactic) 노출 방지는 라우터/직렬화 단에서 이미 막지만,
여기서는 '너무 길거나 깨진 출력'으로부터 UI 를 지키는 게 목적이다.
"""
from __future__ import annotations

import re

_MAX_CHARS = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")


def sanitize_message(text: str) -> str:
    s = str(text or "").strip()
    s = _CONTROL.sub("", s)
    s = _MULTISPACE.sub(" ", s)
    s = _MULTINEWLINE.sub("\n\n", s)
    if len(s) > _MAX_CHARS:
        s = s[:_MAX_CHARS].rstrip() + "…"
    return s
