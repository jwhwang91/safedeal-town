"""
적응형 엔진 DB 접근 계층 (repository).

규칙: 적응형 테이블에 닿는 SQL 은 '전부 이 모듈에만' 둔다.
  - 상위 서비스(adaptive_memory/adaptive_selector/라우터)는 이 함수들만 호출한다.
  - 나중에 PostgreSQL 로 옮길 때 이 파일의 DB 계층만 바꾸면 된다.

이식성 원칙:
  - 기본키는 앱에서 UUID 문자열로 만든다 (SQLite autoincrement 에 의존 안 함).
  - 타임스탬프는 ISO-8601 UTC 문자열.
  - JSON 페이로드는 TEXT 컬럼에 JSON 으로 저장 (PostgreSQL JSONB 로 무손실 이전 가능).
  - SQLite 전용 동작에 핵심 로직을 의존시키지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


# ============================================================
#  공용 헬퍼 (이식성)
# ============================================================
def new_id() -> str:
    """앱 레벨 UUID 문자열 기본키 (DB autoincrement 비의존)."""
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    """ISO-8601 UTC 타임스탬프 문자열."""
    return datetime.now(timezone.utc).isoformat()


def json_dumps(obj) -> str:
    return json.dumps(obj if obj is not None else None, ensure_ascii=False)


def json_loads(text, default):
    if not text:
        return default
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default
    return data


# ============================================================
#  스키마 (멱등 생성) — migrations.run_migrations 에서 호출
# ============================================================
def create_adaptive_tables(conn: sqlite3.Connection) -> None:
    """적응형 테이블을 멱등하게 만든다 (기존 데이터 보존)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_session_outcomes (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            game_role TEXT NOT NULL,
            counterparty_kind TEXT NOT NULL,
            persona_id TEXT,
            persona_family TEXT,
            scenario_type TEXT,
            category TEXT,
            item_name TEXT,
            difficulty TEXT,
            final_decision TEXT,
            verdict TEXT,
            correct INTEGER NOT NULL DEFAULT 0,
            score INTEGER NOT NULL DEFAULT 0,
            detected_patterns_json TEXT NOT NULL DEFAULT '[]',
            missed_patterns_json TEXT NOT NULL DEFAULT '[]',
            resisted_patterns_json TEXT NOT NULL DEFAULT '[]',
            failed_patterns_json TEXT NOT NULL DEFAULT '[]',
            checklist_json TEXT NOT NULL DEFAULT '{}',
            reward_summary_json TEXT NOT NULL DEFAULT '{}',
            turn_count INTEGER NOT NULL DEFAULT 0,
            flag_count INTEGER NOT NULL DEFAULT 0,
            coaching_summary TEXT,
            transcript_digest TEXT,
            redacted_transcript_json TEXT,
            safety_tags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_user_training_memory (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            game_role TEXT NOT NULL,
            pattern_key TEXT NOT NULL,
            pattern_family TEXT NOT NULL,
            times_seen INTEGER NOT NULL DEFAULT 0,
            times_detected INTEGER NOT NULL DEFAULT 0,
            times_missed INTEGER NOT NULL DEFAULT 0,
            times_resisted INTEGER NOT NULL DEFAULT 0,
            times_failed INTEGER NOT NULL DEFAULT 0,
            recent_seen_count INTEGER NOT NULL DEFAULT 0,
            last_seen_at TEXT,
            mastery_score REAL NOT NULL DEFAULT 0.0,
            priority_score REAL NOT NULL DEFAULT 0.5,
            avoid_repetition_until TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, game_role, pattern_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_persona_evolution_events (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            game_role TEXT NOT NULL,
            new_session_id TEXT,
            selected_persona_family TEXT,
            selected_patterns_json TEXT NOT NULL DEFAULT '[]',
            avoided_patterns_json TEXT NOT NULL DEFAULT '[]',
            difficulty_adjustment TEXT,
            reason TEXT,
            provider TEXT NOT NULL DEFAULT 'template',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_pattern_catalog_snapshot (
            pattern_key TEXT PRIMARY KEY,
            pattern_family TEXT NOT NULL,
            game_role TEXT NOT NULL,
            label TEXT NOT NULL,
            red_flag TEXT,
            safe_counter TEXT,
            severity INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_session_adaptive_context (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            selected_patterns_json TEXT NOT NULL DEFAULT '[]',
            avoided_patterns_json TEXT NOT NULL DEFAULT '[]',
            difficulty_adjustment TEXT,
            persona_variant_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_outcomes_user "
        "ON ai_session_outcomes(user_id, game_role)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_memory_user "
        "ON ai_user_training_memory(user_id, game_role)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_evo_user "
        "ON ai_persona_evolution_events(user_id, game_role)"
    )


def seed_pattern_catalog(conn: sqlite3.Connection) -> None:
    """분류표(pattern_taxonomy)를 스냅샷 테이블에 안전 UPSERT 한다 (멱등)."""
    from app.ai import pattern_taxonomy

    now = utcnow_iso()
    for p in pattern_taxonomy.ALL_PATTERNS:
        conn.execute(
            """
            INSERT INTO ai_pattern_catalog_snapshot
                (pattern_key, pattern_family, game_role, label, red_flag,
                 safe_counter, severity, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pattern_key) DO UPDATE SET
                pattern_family = excluded.pattern_family,
                game_role = excluded.game_role,
                label = excluded.label,
                red_flag = excluded.red_flag,
                safe_counter = excluded.safe_counter,
                severity = excluded.severity,
                updated_at = excluded.updated_at
            """,
            (p["pattern_key"], p["pattern_family"], p["game_role"], p["label"],
             p.get("red_flag", ""), p.get("safe_counter", ""),
             int(p.get("severity", 1)), now),
        )


# ============================================================
#  세션 결과 (ai_session_outcomes)
# ============================================================
_OUTCOME_COLUMNS = [
    "id", "user_id", "session_id", "game_role", "counterparty_kind",
    "persona_id", "persona_family", "scenario_type", "category", "item_name",
    "difficulty", "final_decision", "verdict", "correct", "score",
    "detected_patterns_json", "missed_patterns_json", "resisted_patterns_json",
    "failed_patterns_json", "checklist_json", "reward_summary_json",
    "turn_count", "flag_count", "coaching_summary", "transcript_digest",
    "redacted_transcript_json", "safety_tags_json", "created_at",
]


def insert_session_outcome(conn: sqlite3.Connection, row: dict) -> str:
    """ai_session_outcomes 한 줄 삽입. id 가 없으면 만들어 채운다. id 반환."""
    data = dict(row)
    data.setdefault("id", new_id())
    data.setdefault("created_at", utcnow_iso())
    cols = [c for c in _OUTCOME_COLUMNS if c in data]
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO ai_session_outcomes ({', '.join(cols)}) VALUES ({placeholders})",
        [data[c] for c in cols],
    )
    return data["id"]


def count_completed_outcomes(conn: sqlite3.Connection, user_id: int, game_role: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM ai_session_outcomes WHERE user_id = ? AND game_role = ?",
        (user_id, game_role),
    ).fetchone()
    return int(row["n"]) if row else 0


# ============================================================
#  사용자 훈련 메모리 (ai_user_training_memory)
# ============================================================
def get_training_memory(conn: sqlite3.Connection, user_id: int, game_role: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ai_user_training_memory WHERE user_id = ? AND game_role = ?",
        (user_id, game_role),
    ).fetchall()
    return [dict(r) for r in rows]


def get_memory_row(conn: sqlite3.Connection, user_id: int, game_role: str,
                   pattern_key: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ai_user_training_memory "
        "WHERE user_id = ? AND game_role = ? AND pattern_key = ?",
        (user_id, game_role, pattern_key),
    ).fetchone()
    return dict(row) if row else None


def write_training_memory(conn: sqlite3.Connection, fields: dict) -> None:
    """완성된 메모리 집계 한 줄을 UPSERT 한다 (unique: user_id, game_role, pattern_key).

    증분 계산(카운터/숙련도)은 상위 서비스(adaptive_memory)가 하고, 여기선 저장만 한다.
    """
    f = dict(fields)
    f.setdefault("id", new_id())
    f.setdefault("updated_at", utcnow_iso())
    conn.execute(
        """
        INSERT INTO ai_user_training_memory
            (id, user_id, game_role, pattern_key, pattern_family,
             times_seen, times_detected, times_missed, times_resisted, times_failed,
             recent_seen_count, last_seen_at, mastery_score, priority_score,
             avoid_repetition_until, updated_at)
        VALUES (:id, :user_id, :game_role, :pattern_key, :pattern_family,
             :times_seen, :times_detected, :times_missed, :times_resisted, :times_failed,
             :recent_seen_count, :last_seen_at, :mastery_score, :priority_score,
             :avoid_repetition_until, :updated_at)
        ON CONFLICT(user_id, game_role, pattern_key) DO UPDATE SET
            pattern_family = excluded.pattern_family,
            times_seen = excluded.times_seen,
            times_detected = excluded.times_detected,
            times_missed = excluded.times_missed,
            times_resisted = excluded.times_resisted,
            times_failed = excluded.times_failed,
            recent_seen_count = excluded.recent_seen_count,
            last_seen_at = excluded.last_seen_at,
            mastery_score = excluded.mastery_score,
            priority_score = excluded.priority_score,
            avoid_repetition_until = excluded.avoid_repetition_until,
            updated_at = excluded.updated_at
        """,
        f,
    )


# ============================================================
#  페르소나 진화 이벤트 (ai_persona_evolution_events)
# ============================================================
def insert_evolution_event(conn: sqlite3.Connection, row: dict) -> str:
    data = dict(row)
    data.setdefault("id", new_id())
    data.setdefault("created_at", utcnow_iso())
    conn.execute(
        """
        INSERT INTO ai_persona_evolution_events
            (id, user_id, game_role, new_session_id, selected_persona_family,
             selected_patterns_json, avoided_patterns_json, difficulty_adjustment,
             reason, provider, created_at)
        VALUES (:id, :user_id, :game_role, :new_session_id, :selected_persona_family,
             :selected_patterns_json, :avoided_patterns_json, :difficulty_adjustment,
             :reason, :provider, :created_at)
        """,
        {
            "id": data["id"],
            "user_id": data["user_id"],
            "game_role": data["game_role"],
            "new_session_id": data.get("new_session_id"),
            "selected_persona_family": data.get("selected_persona_family"),
            "selected_patterns_json": data.get("selected_patterns_json", "[]"),
            "avoided_patterns_json": data.get("avoided_patterns_json", "[]"),
            "difficulty_adjustment": data.get("difficulty_adjustment"),
            "reason": data.get("reason"),
            "provider": data.get("provider", "template"),
            "created_at": data["created_at"],
        },
    )
    return data["id"]


def get_recent_evolution_events(conn: sqlite3.Connection, user_id: int,
                                game_role: str, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ai_persona_evolution_events "
        "WHERE user_id = ? AND game_role = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, game_role, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
#  세션 적응 컨텍스트 (ai_session_adaptive_context) — 서버 전용
# ============================================================
def insert_adaptive_context(conn: sqlite3.Connection, session_id: str, user_id: int,
                            selected_patterns, avoided_patterns,
                            difficulty_adjustment, persona_variant) -> None:
    # 이식성: SQLite 전용 'INSERT OR REPLACE' 대신 SQLite 3.24+/PostgreSQL 공통 UPSERT 사용.
    conn.execute(
        """
        INSERT INTO ai_session_adaptive_context
            (session_id, user_id, selected_patterns_json, avoided_patterns_json,
             difficulty_adjustment, persona_variant_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            user_id = excluded.user_id,
            selected_patterns_json = excluded.selected_patterns_json,
            avoided_patterns_json = excluded.avoided_patterns_json,
            difficulty_adjustment = excluded.difficulty_adjustment,
            persona_variant_json = excluded.persona_variant_json,
            created_at = excluded.created_at
        """,
        (session_id, user_id, json_dumps(selected_patterns or []),
         json_dumps(avoided_patterns or []), difficulty_adjustment,
         json_dumps(persona_variant or {}), utcnow_iso()),
    )


def get_adaptive_context(conn: sqlite3.Connection, session_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ai_session_adaptive_context WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "selected_patterns": json_loads(row["selected_patterns_json"], []),
        "avoided_patterns": json_loads(row["avoided_patterns_json"], []),
        "difficulty_adjustment": row["difficulty_adjustment"],
        "persona_variant": json_loads(row["persona_variant_json"], {}),
        "created_at": row["created_at"],
    }


# ============================================================
#  리셋 (현재 로그인 사용자 전용)
# ============================================================
def reset_user_adaptive(conn: sqlite3.Connection, user_id: int) -> dict:
    """현재 사용자의 적응형 데이터만 지운다. 계정/거래기록은 건드리지 않는다."""
    counts = {}
    for table in (
        "ai_session_outcomes",
        "ai_user_training_memory",
        "ai_persona_evolution_events",
    ):
        cur = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        counts[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    # 세션 적응 컨텍스트도 사용자 기준으로 정리 (서버 전용)
    cur = conn.execute(
        "DELETE FROM ai_session_adaptive_context WHERE user_id = ?", (user_id,)
    )
    counts["ai_session_adaptive_context"] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return counts
