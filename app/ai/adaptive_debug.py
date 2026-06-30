"""
적응형 엔진 디버그/설명 보조 (선택).

ADAPTIVE_DEBUG_EXPLAIN=true 일 때만 라우터가 이 모듈을 통해 '왜 이 시나리오가 골라졌는지'
설명 데이터를 노출한다. 기본값(false)에서는 어떤 숨은 적응 데이터도 프론트로 가지 않는다.

⚠️ 이 데이터는 내부 진단용이다. 결과 화면 전에 프론트로 보내지 않는다.
"""
from __future__ import annotations

import sqlite3

from app.ai import adaptive_repository as repo
from app.config import get_settings


def is_enabled() -> bool:
    return bool(get_settings().adaptive_debug_explain)


def explain_user(conn: sqlite3.Connection, user_id: int, game_role: str) -> dict:
    """최근 선택 이벤트 + 컨텍스트 요약 (디버그 전용)."""
    role = "seller" if game_role == "seller" else "buyer"
    events = repo.get_recent_evolution_events(conn, user_id, role, limit=10)
    return {
        "game_role": role,
        "recent_events": [
            {
                "new_session_id": e.get("new_session_id"),
                "selected_persona_family": e.get("selected_persona_family"),
                "selected_patterns": repo.json_loads(e.get("selected_patterns_json"), []),
                "avoided_patterns": repo.json_loads(e.get("avoided_patterns_json"), []),
                "difficulty_adjustment": e.get("difficulty_adjustment"),
                "reason": e.get("reason"),
                "provider": e.get("provider"),
                "created_at": e.get("created_at"),
            }
            for e in events
        ],
    }
