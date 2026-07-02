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
    # 동적 NPC/매물 (정답지는 서버 전용 — 클라이언트로 직렬화되지 않음)
    _add_column_if_missing(conn, "trade_sessions", "session_npc_json", "session_npc_json TEXT")
    _add_column_if_missing(conn, "trade_sessions", "market_seed_json", "market_seed_json TEXT")
    # 이 거래에 연결된 활성 미션(선택)
    _add_column_if_missing(conn, "trade_sessions", "active_mission_id", "active_mission_id TEXT")

    # ---- trade_results: 모드 구분 + 동적 NPC 기록 + 체크리스트/보상 ----
    _add_column_if_missing(
        conn, "trade_results", "game_role",
        "game_role TEXT NOT NULL DEFAULT 'buyer'",
    )
    _add_column_if_missing(conn, "trade_results", "counterparty_name", "counterparty_name TEXT")
    _add_column_if_missing(conn, "trade_results", "item_name", "item_name TEXT")
    _add_column_if_missing(conn, "trade_results", "checklist_json", "checklist_json TEXT")
    _add_column_if_missing(conn, "trade_results", "reward_items_json", "reward_items_json TEXT")

    # ---- active_spawns: 동적 생성 NPC/매물 (공개 필드만 직렬화) ----
    _add_column_if_missing(conn, "active_spawns", "dynamic_json", "dynamic_json TEXT")

    # ---- chat_messages: 미션(proof_first_buyer)이 생성한 인증사진 (data URI, 선택) ----
    _add_column_if_missing(conn, "chat_messages", "image_data_uri", "image_data_uri TEXT")

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

    # ---- 회원별 마켓 선호/판매글 ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_market_preferences (
            user_id                INTEGER PRIMARY KEY,
            buyer_category         TEXT,
            buyer_price_preference TEXT,
            buyer_trade_preference TEXT,
            seller_listing_json    TEXT,
            updated_at             TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    # ---- 판매자 모드 인바운드 문의 (스키마는 schema.sql 과 byte-for-byte 동일하게 유지) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seller_inquiries (
            id              TEXT PRIMARY KEY,
            user_id         INTEGER NOT NULL,
            spawn_id        TEXT NOT NULL,
            npc_id          TEXT NOT NULL,
            listing_title   TEXT,
            inquiry_preview TEXT,
            status          TEXT NOT NULL DEFAULT 'waiting',
            session_id      TEXT,
            created_at      TEXT NOT NULL,
            expires_at      TEXT NOT NULL,
            FOREIGN KEY (user_id)  REFERENCES users(id)         ON DELETE CASCADE,
            FOREIGN KEY (spawn_id) REFERENCES active_spawns(id) ON DELETE CASCADE,
            FOREIGN KEY (npc_id)   REFERENCES npcs(id)          ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_seller_inq_user "
        "ON seller_inquiries(user_id, status)"
    )

    # ---- 미션 / 돌발 퀘스트 (스키마는 schema.sql 과 동일하게 유지) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_active_missions (
            id           TEXT PRIMARY KEY,
            user_id      INTEGER NOT NULL,
            session_id   TEXT,
            mission_key  TEXT NOT NULL,
            game_role    TEXT NOT NULL,
            mission_json TEXT NOT NULL DEFAULT '{}',
            status       TEXT NOT NULL DEFAULT 'active',
            reward_json  TEXT NOT NULL DEFAULT '{}',
            created_at   TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_missions_user "
        "ON user_active_missions(user_id, game_role, status)"
    )

    # ---- 인벤토리: 아이템 정의 / 보유 / 장착 ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            item_type   TEXT NOT NULL,
            rarity      TEXT NOT NULL,
            slot        TEXT,
            description TEXT,
            effect_key  TEXT,
            visual_json TEXT,
            created_at  TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_items (
            user_id     INTEGER NOT NULL,
            item_id     TEXT NOT NULL,
            quantity    INTEGER NOT NULL DEFAULT 1,
            acquired_at TEXT NOT NULL,
            PRIMARY KEY (user_id, item_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_equipment (
            user_id     INTEGER NOT NULL,
            slot        TEXT NOT NULL,
            item_id     TEXT NOT NULL,
            equipped_at TEXT NOT NULL,
            PRIMARY KEY (user_id, slot),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_items_user ON user_items(user_id)"
    )

    # ---- (선택) 매물 씨앗 / 트렌드 캐시 (비식별 시장 맥락만) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_listing_seeds (
            id                TEXT PRIMARY KEY,
            source_type       TEXT,
            category          TEXT,
            product_name      TEXT,
            title_hint        TEXT,
            price_hint        INTEGER,
            market_price_hint INTEGER,
            condition_hint    TEXT,
            metadata_json     TEXT,
            created_at        TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_trends (
            id         TEXT PRIMARY KEY,
            category   TEXT,
            trend_json TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    # ============================================================
    #  방어 훈련 플랫폼 레이어 (진단 / 리포트 / 커뮤니티 / 시나리오 뱅크 / 기관)
    #  전부 멱등(CREATE TABLE IF NOT EXISTS) — 기존 데이터 보존.
    #  스키마는 schema.sql 과 동일하게 유지할 것.
    # ============================================================

    # ---- Phase 1: 사기 취약도 진단 (baseline / post-training / quick-check) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_question_bank (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            risk_family TEXT NOT NULL,
            question_type TEXT NOT NULL,
            prompt TEXT NOT NULL,
            options_json TEXT NOT NULL DEFAULT '[]',
            correct_answer_json TEXT NOT NULL DEFAULT '{}',
            explanation TEXT,
            difficulty TEXT NOT NULL DEFAULT 'medium',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_assessment_sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            assessment_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            score INTEGER,
            dimension_scores_json TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_assessment_answers (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            answer_json TEXT NOT NULL DEFAULT '{}',
            is_correct INTEGER NOT NULL DEFAULT 0,
            score_delta INTEGER NOT NULL DEFAULT 0,
            detected_dimensions_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES user_assessment_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assess_sessions_user "
        "ON user_assessment_sessions(user_id, assessment_type, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assess_answers_session "
        "ON user_assessment_answers(session_id)"
    )

    # ---- Phase 4: 커뮤니티 피해 사례 (비식별 후 저장) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS community_cases (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            platform TEXT,
            loss_amount_range TEXT,
            incident_date_text TEXT,
            redacted_body TEXT NOT NULL,
            raw_body_stored INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            labels_json TEXT NOT NULL DEFAULT '[]',
            extracted_risk_signals_json TEXT NOT NULL DEFAULT '[]',
            scenario_candidate_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS community_case_reactions (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            reaction_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(case_id, user_id, reaction_type),
            FOREIGN KEY (case_id) REFERENCES community_cases(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS community_case_comments (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            redacted_comment TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'visible',
            created_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES community_cases(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS community_case_reports (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            user_id INTEGER,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES community_cases(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_cases_status "
        "ON community_cases(status, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_comments_case "
        "ON community_case_comments(case_id, status)"
    )

    # ---- Phase 6: 방어 시나리오 뱅크 (비식별·픽션화된 훈련 시나리오 후보) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_bank (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_case_id TEXT,
            category TEXT NOT NULL,
            risk_family TEXT NOT NULL,
            title TEXT NOT NULL,
            scenario_summary TEXT NOT NULL,
            red_flags_json TEXT NOT NULL DEFAULT '[]',
            safe_counters_json TEXT NOT NULL DEFAULT '[]',
            difficulty TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_labels (
            id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            label_key TEXT NOT NULL,
            label_value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at TEXT NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenario_bank(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenario_bank_lookup "
        "ON scenario_bank(status, category, risk_family)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenario_labels_scenario "
        "ON scenario_labels(scenario_id)"
    )

    # ---- Phase 10: 기관 / 코호트 데모 (집계 리포트용) ----
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            org_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cohorts (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_members (
            id TEXT PRIMARY KEY,
            cohort_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            display_alias TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(cohort_id, user_id),
            FOREIGN KEY (cohort_id) REFERENCES cohorts(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cohort_members_cohort "
        "ON cohort_members(cohort_id)"
    )

    # 진단 문항 시드 + 데모 시나리오 시드 (멱등 UPSERT — best-effort).
    # 실패해도 기존 게임/데이터는 보존한다.
    try:
        from app.assessment import question_bank as _qbank

        _qbank.seed_assessment_questions(conn)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "assessment question seed skipped: %s", exc, exc_info=True
        )
    try:
        from app.scenarios import scenario_bank as _sbank

        _sbank.seed_demo_scenarios(conn)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "scenario bank seed skipped: %s", exc, exc_info=True
        )

    # ---- 적응형 시나리오 엔진 (방어 훈련 커리큘럼) ----
    # 멱등 생성 + 분류표 스냅샷 안전 UPSERT. SQL 은 adaptive_repository(=DB 계층)에 모아둔다.
    # 실패해도 기존 게임은 그대로 동작해야 하므로 전체를 best-effort 로 감싼다.
    try:
        from app.ai import adaptive_repository

        adaptive_repository.create_adaptive_tables(conn)
        adaptive_repository.seed_pattern_catalog(conn)
    except Exception as exc:
        # 적응형 테이블 생성/시드가 어떤 이유로든 실패해도 기존 데이터/게임은 보존된다.
        # 단, 결정적 결함(DDL 오타 등)이 조용히 묻히지 않도록 경고는 남긴다.
        import logging

        logging.getLogger(__name__).warning(
            "adaptive schema setup skipped: %s", exc, exc_info=True
        )

    conn.commit()
