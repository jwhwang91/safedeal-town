"""
시나리오 뱅크 ↔ 훈련 연결 (Phase F).

⚠️ 안전 원칙: 이 모듈은 NPC 의 role/tactics(정답지)나 페르소나 생성을 '절대' 바꾸지 않는다.
승인된(approved) 시나리오 뱅크의 seed 를 '비권위적 참고 힌트'로만 골라, 서버 전용
텔레메트리(적응형 진화 이벤트)에 남긴다. 그래서:
  - 승인된 시나리오 seed 가 있으면 이번 훈련 맥락에 '연결'되어 이후 추천/설명에 쓰인다.
  - seed 가 없거나 어떤 예외가 나도 기존 NPC/페르소나 생성 흐름이 그대로 유지된다(폴백).

즉 '승인된 시나리오 seed 가 미래 훈련을 informed 하되, 기존 NPC 생성을 깨지 않는다'는
요구를 규칙기반·비침습적으로 만족한다. 실제 대화 상대(정답지)는 기존 로직이 정한다.
"""
from __future__ import annotations

import sqlite3


def pick_scenario_seed(
    conn: sqlite3.Connection,
    user_id: int,
    game_role: str,
    active_mission_key: str | None = None,
) -> dict | None:
    """이번 훈련에 '참고'할 승인된 시나리오 seed 하나를 고른다 (없으면 None).

    사용자 약점 차원 + 활성 미션을 고려해 승인된 시나리오만 추천한다.
    미승인/커뮤니티 원문은 절대 쓰지 않는다 (retriever 가 approved 만 반환).
    """
    try:
        from app.scenarios import retriever

        recs = retriever.recommend_scenarios(
            conn, user_id, active_mission_key=active_mission_key, limit=1
        )
        if not recs:
            return None
        s = recs[0]
        return {
            "scenario_id": s.get("id"),
            "title": s.get("title"),
            "category": s.get("category"),
            "risk_family": s.get("risk_family"),
            "source": "scenario_bank",
        }
    except Exception:
        # 어떤 실패도 훈련 흐름에 영향 주지 않는다.
        return None


def link_seed_to_session(
    conn: sqlite3.Connection,
    user_id: int,
    session_id: str,
    game_role: str,
    active_mission_key: str | None = None,
) -> dict | None:
    """세션 시작 시 승인된 시나리오 seed 를 골라 서버 전용 텔레메트리로 남긴다.

    반환: 고른 seed(dict) 또는 None. 커밋은 호출자(start_chat)가 한다.
    NPC/페르소나/정답지는 건드리지 않는다. best-effort — 실패해도 조용히 무시.
    """
    seed = pick_scenario_seed(conn, user_id, game_role, active_mission_key)
    if not seed:
        return None
    try:
        from app.ai import adaptive_repository as repo

        repo.insert_evolution_event(conn, {
            "user_id": user_id,
            "game_role": game_role,
            "new_session_id": session_id,
            "selected_persona_family": seed.get("risk_family"),
            "selected_patterns_json": repo.json_dumps([]),
            "avoided_patterns_json": repo.json_dumps([]),
            "difficulty_adjustment": "same",
            "reason": f"scenario_bank_seed:{seed.get('title')}",
            "provider": "scenario_bank",
        })
    except Exception:
        # 텔레메트리 기록 실패는 훈련에 영향 없음.
        pass
    return seed
