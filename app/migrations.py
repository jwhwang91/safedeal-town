"""
스키마 마이그레이션 (멱등).

schema.sql 은 '처음 설치할 때' 테이블을 만든다(CREATE TABLE IF NOT EXISTS).
하지만 이미 깔려서 돌아가던 DB 에는 새 컬럼/새 테이블이 없을 수 있다.
이 모듈이 그 간극을 메운다:

  - 기존 테이블에 빠진 컬럼을 ALTER TABLE 로 더한다 (이미 있으면 건너뜀).
  - 새 테이블은 CREATE TABLE IF NOT EXISTS 로 만든다.

전부 멱등이라 앱이 켜질 때마다 여러 번 호출돼도 안전하고,
기존 런타임 데이터(회원/거래기록 등)를 절대 지우지 않는다.

initialize_database() 안에서 schema.sql 실행 직후에 한 번 불린다.
"""
from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, ddl: str
) -> None:
    """table 에 column 이 없으면 'ALTER TABLE table ADD COLUMN <ddl>' 실행."""
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def run_migrations(conn: sqlite3.Connection) -> None:
    # ---- users: 게임 역할 / 아바타 / 판매 카테고리 / 셋업 완료여부 ----
    _add_column_if_missing(conn, "users", "game_role", "game_role TEXT")
    _add_column_if_missing(conn, "users", "avatar_json", "avatar_json TEXT")
    _add_column_if_missing(conn, "users", "seller_category", "seller_category TEXT")
    _add_column_if_missing(
        conn, "users", "setup_completed",
        "setup_completed INTEGER NOT NULL DEFAULT 0",
    )
    # ---- 재화 시스템: 코인 + 모은 아이템(거래로 얻고, 사기/과환불로 잃는다) ----
    # 신규 설치는 schema.sql 의 users 정의에 이미 포함됨. 여기 둔 건 그 전에 만들어진
    # 기존 DB 를 보강하기 위함 (멱등 — 이미 있으면 건너뜀). 두 정의는 동일하게 유지할 것.
    _add_column_if_missing(conn, "users", "coins", "coins INTEGER NOT NULL DEFAULT 100")
    _add_column_if_missing(conn, "users", "inventory_json", "inventory_json TEXT")

    # ---- npcs: 종류(판매자/구매자) / 비주얼 테마 / 카테고리 / 스폰 행동 ----
    _add_column_if_missing(
        conn, "npcs", "npc_kind",
        "npc_kind TEXT NOT NULL DEFAULT 'seller'",
    )
    _add_column_if_missing(conn, "npcs", "visual_theme", "visual_theme TEXT")
    _add_column_if_missing(conn, "npcs", "category", "category TEXT")
    _add_column_if_missing(conn, "npcs", "spawn_behavior_json", "spawn_behavior_json TEXT")

    # ---- trade_sessions: 어느 모드의 거래였는지 맥락 보존 ----
    _add_column_if_missing(conn, "trade_sessions", "game_role", "game_role TEXT")
    _add_column_if_missing(conn, "trade_sessions", "counterparty_kind", "counterparty_kind TEXT")
    _add_column_if_missing(conn, "trade_sessions", "scenario_type", "scenario_type TEXT")
    _add_column_if_missing(conn, "trade_sessions", "spawn_instance_id", "spawn_instance_id TEXT")

    # ---- trade_results: 모드 구분 (전적실에서 버디 라벨을 올바로 보여주려고) ----
    _add_column_if_missing(
        conn, "trade_results", "game_role",
        "game_role TEXT NOT NULL DEFAULT 'buyer'",
    )

    # ---- 활성 스폰 테이블 (백엔드가 NPC 등장/소멸을 관리) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS active_spawns (
            id          TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            npc_id      TEXT NOT NULL,
            game_role   TEXT NOT NULL,
            x           INTEGER NOT NULL,
            y           INTEGER NOT NULL,
            spawned_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (npc_id)  REFERENCES npcs(id)  ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spawns_user ON active_spawns(user_id, status)"
    )

    # ---- 맵 프로필 테이블 (회원별 동네 한 장을 캐싱) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS map_profiles (
            user_id    INTEGER PRIMARY KEY,
            provider   TEXT NOT NULL,
            lat        REAL,
            lng        REAL,
            seed       TEXT NOT NULL,
            map_json   TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
