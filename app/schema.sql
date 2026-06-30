-- ============================================================
--  SafeDeal Town 데이터베이스 스키마 (SQLite)
--  엔진을 처음 켤 때 이 파일을 그대로 실행해서 테이블을 만든다.
--  관계: users 1 ──< trade_sessions >── 1 npcs
--        trade_sessions 1 ──< chat_messages
--        trade_sessions 1 ──1 trade_results
--        users 1 ──< player_npc_progress >── 1 npcs
-- ============================================================

PRAGMA foreign_keys = ON;

-- ----- 회원 -----
CREATE TABLE IF NOT EXISTS users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT NOT NULL UNIQUE,
    display_name          TEXT NOT NULL,
    email                 TEXT,
    password_hash         TEXT NOT NULL,          -- scrypt 해시 (평문 저장 안 함)
    password_salt         TEXT NOT NULL,          -- 회원마다 다른 salt
    level                 INTEGER NOT NULL DEFAULT 1,
    xp                    INTEGER NOT NULL DEFAULT 0,
    trust_score           INTEGER NOT NULL DEFAULT 50,  -- 0~100, 사기 당하면 깎임
    coins                 INTEGER NOT NULL DEFAULT 100, -- 재화: 정상거래로 벌고, 사기/과환불로 잃음
    inventory_json        TEXT,                         -- 모은 아이템(JSON 배열). 사기/과환불 시 최근 아이템 상실
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until          TEXT,                   -- 로그인 5회 실패 시 잠금 해제 시각
    game_role             TEXT,                   -- 'buyer' | 'seller' (셋업 전 NULL)
    avatar_json           TEXT,                   -- 아바타 커스터마이즈 (피부/모자/상의/하의/액세서리)
    seller_category       TEXT,                   -- 판매자 모드일 때 취급 카테고리
    setup_completed       INTEGER NOT NULL DEFAULT 0,  -- 역할/아바타 셋업을 마쳤나 (0/1)
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    last_login_at         TEXT
);

-- ----- NPC (AI 판매자) -----
-- role / tactics 는 "정답지". 클라이언트에는 절대 안 내려보낸다.
CREATE TABLE IF NOT EXISTS npcs (
    id             TEXT PRIMARY KEY,              -- 예: "minsu_deposit"
    name           TEXT NOT NULL,
    item_name      TEXT NOT NULL,
    item_category  TEXT NOT NULL,
    listing_price  INTEGER NOT NULL,              -- 판매자가 부른 값
    market_price   INTEGER NOT NULL,              -- 실제 시세 (참고용)
    location       TEXT NOT NULL,
    role           TEXT NOT NULL,                 -- 'scammer' | 'honest'
    difficulty     TEXT NOT NULL,                 -- 'easy' | 'medium' | 'hard'
    persona_json   TEXT NOT NULL,                 -- 성격/배경/말투 (AI 프롬프트 재료)
    tactics_json   TEXT NOT NULL,                 -- 사기수법/행동 플레이북 (정답지)
    sprite_color   TEXT NOT NULL,                 -- 게임 화면용 캐릭터 색
    spawn_x        INTEGER NOT NULL,              -- (참고용) 기본 좌판 위치 — 실제 등장은 active_spawns 가 관리
    spawn_y        INTEGER NOT NULL,
    npc_kind       TEXT NOT NULL DEFAULT 'seller',-- 'seller'(구매자 모드용) | 'buyer'(판매자 모드용)
    visual_theme   TEXT,                          -- 카테고리/역할별 그림 테마 (부스 소품 등)
    category       TEXT,                          -- 'electronics' | 'camping' | 'beauty' | ...
    spawn_behavior_json TEXT,                      -- 스폰 동작 힌트 (선택)
    created_at     TEXT NOT NULL
);

-- ----- 거래 세션 (NPC 한 명과의 대화 한 판) -----
CREATE TABLE IF NOT EXISTS trade_sessions (
    id              TEXT PRIMARY KEY,             -- uuid
    user_id         INTEGER NOT NULL,
    npc_id          TEXT NOT NULL,
    status          TEXT NOT NULL,                -- 'active' | 'resolved'
    player_decision TEXT,                         -- 모드별 최종 결정 (buy/... 또는 complete_sale/...)
    game_role         TEXT,                       -- 이 거래에서 플레이어의 역할 (buyer|seller)
    counterparty_kind TEXT,                       -- 상대 NPC 종류 (seller|buyer)
    scenario_type     TEXT,                       -- 시나리오 태그 (예: refund_villain)
    spawn_instance_id TEXT,                       -- 어느 스폰에서 시작했나 (선택)
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (npc_id)  REFERENCES npcs(id)  ON DELETE CASCADE
);

-- ----- 채팅 메시지 -----
CREATE TABLE IF NOT EXISTS chat_messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        TEXT NOT NULL,
    turn_index        INTEGER NOT NULL,
    speaker           TEXT NOT NULL,              -- 'player' | 'npc'
    content           TEXT NOT NULL,
    tactic            TEXT,                       -- NPC가 이 메시지에서 쓴 수법(있으면). 정답지.
    flagged_by_player INTEGER NOT NULL DEFAULT 0, -- 플레이어가 🚩 눌렀나 (0/1)
    created_at        TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES trade_sessions(id) ON DELETE CASCADE
);

-- ----- 거래 결과 (심판 AI의 채점 결과) -----
CREATE TABLE IF NOT EXISTS trade_results (
    session_id          TEXT PRIMARY KEY,
    user_id             INTEGER NOT NULL,
    npc_id              TEXT NOT NULL,
    game_role           TEXT NOT NULL DEFAULT 'buyer',  -- 어느 모드의 결과인지
    verdict             TEXT NOT NULL,            -- 모드별 결과 라벨 (good_catch.. / fair_sale..)
    correct             INTEGER NOT NULL,         -- 판단이 옳았나 (0/1)
    score               INTEGER NOT NULL,         -- 0~100
    detected_flags_json TEXT NOT NULL,            -- 플레이어가 잡아낸 위험신호
    missed_flags_json   TEXT NOT NULL,            -- 놓친 위험신호
    coaching            TEXT NOT NULL,            -- 코치 AI 한마디
    xp_delta            INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES trade_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)    REFERENCES users(id)          ON DELETE CASCADE
);

-- ----- 플레이어별 NPC 진행도 -----
CREATE TABLE IF NOT EXISTS player_npc_progress (
    user_id        INTEGER NOT NULL,
    npc_id         TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    best_score     INTEGER NOT NULL DEFAULT 0,
    cleared        INTEGER NOT NULL DEFAULT 0,    -- 0/1
    last_played_at TEXT,
    PRIMARY KEY (user_id, npc_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (npc_id)  REFERENCES npcs(id)  ON DELETE CASCADE
);

-- ----- 활성 스폰 (백엔드가 NPC 등장/소멸을 관리) -----
CREATE TABLE IF NOT EXISTS active_spawns (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    npc_id      TEXT NOT NULL,
    game_role   TEXT NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    spawned_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'expired' | 'engaged'
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (npc_id)  REFERENCES npcs(id)  ON DELETE CASCADE
);

-- ----- 맵 프로필 (회원별 동네 한 장 캐싱) -----
CREATE TABLE IF NOT EXISTS map_profiles (
    user_id    INTEGER PRIMARY KEY,
    provider   TEXT NOT NULL,
    lat        REAL,
    lng        REAL,
    seed       TEXT NOT NULL,
    map_json   TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user    ON trade_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_results_user     ON trade_results(user_id);
CREATE INDEX IF NOT EXISTS idx_spawns_user      ON active_spawns(user_id, status);
