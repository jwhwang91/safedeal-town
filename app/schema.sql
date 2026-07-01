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
    session_npc_json  TEXT,                       -- 동적 생성된 NPC(정답지 포함, 서버 전용). 없으면 npcs 테이블 사용
    market_seed_json  TEXT,                       -- 이 거래에 쓰인 매물 씨앗(비식별 시장 맥락)
    active_mission_id TEXT,                       -- 이 거래에 연결된 활성 미션(선택, user_active_missions.id)
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
    counterparty_name   TEXT,                     -- 상대 표시 이름 (동적 NPC 기록 보존용)
    item_name           TEXT,                     -- 거래 물건 이름 (동적 NPC 기록 보존용)
    checklist_json      TEXT,                     -- 플레이어가 체크한 거래 체크리스트 상태
    reward_items_json   TEXT,                     -- 이 거래로 획득한 인벤토리 아이템(공개 정보)
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
    dynamic_json TEXT,                            -- 동적 생성 NPC/매물(정답지 포함, 서버 전용). 공개 필드만 직렬화됨
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

-- ----- 회원별 마켓 선호/판매글 (구매 위시리스트 + 판매자 매물) -----
CREATE TABLE IF NOT EXISTS user_market_preferences (
    user_id                INTEGER PRIMARY KEY,
    buyer_category         TEXT,                  -- 구매자 모드: 오늘 찾는 카테고리
    buyer_price_preference TEXT,                  -- bargain | fair | premium
    buyer_trade_preference TEXT,                  -- direct | delivery | safepay | any
    seller_listing_json    TEXT,                  -- 판매자 모드: 내 판매글(상품/상태/가격/구성품/증거)
    updated_at             TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ----- 판매자 모드 인바운드 문의 (구매자 NPC 가 내 판매글에 남긴 문의 카드) -----
-- 백엔드가 페이싱(간격/최대수)을 관리한다. spawn 이 사라지면 FK CASCADE 로 문의도 사라진다.
-- npc_id(앵커=정답지)는 서버 전용 — 클라이언트로는 절대 직렬화하지 않는다.
CREATE TABLE IF NOT EXISTS seller_inquiries (
    id              TEXT PRIMARY KEY,                -- uuid
    user_id         INTEGER NOT NULL,                -- 판매자(플레이어)
    spawn_id        TEXT NOT NULL,                   -- 어느 활성 스폰(구매자 NPC)에서 왔나
    npc_id          TEXT NOT NULL,                   -- 앵커 NPC (정답지 — 클라이언트 비노출)
    listing_title   TEXT,                            -- 당시 내 판매글 제목
    inquiry_preview TEXT,                            -- 중립 첫 문의 미리보기 (구매자 유형 비노출)
    status          TEXT NOT NULL DEFAULT 'waiting',  -- 'waiting' | 'accepted' | 'expired'
    session_id      TEXT,                            -- accept 시 시작된 거래 세션 (선택)
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    FOREIGN KEY (user_id)  REFERENCES users(id)         ON DELETE CASCADE,
    FOREIGN KEY (spawn_id) REFERENCES active_spawns(id) ON DELETE CASCADE,
    FOREIGN KEY (npc_id)   REFERENCES npcs(id)          ON DELETE CASCADE
);

-- ----- 미션 / 돌발 퀘스트 (플레이어가 수락한 활성 미션) -----
CREATE TABLE IF NOT EXISTS user_active_missions (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    session_id   TEXT,
    mission_key  TEXT NOT NULL,
    game_role    TEXT NOT NULL,
    mission_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'completed' | 'failed' | 'skipped'
    reward_json  TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ----- 인벤토리 아이템 정의 (거래 도구/배지/코스튬) -----
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    item_type   TEXT NOT NULL,                    -- cosmetic | badge | tool | profile_frame | checklist
    rarity      TEXT NOT NULL,                    -- common | uncommon | rare | epic | legendary
    slot        TEXT,                             -- hat | shirt | pants | accessory | badge | tool_1 | tool_2 | profile_frame
    description TEXT,
    effect_key  TEXT,                             -- 도구 효과 키 (price_radar 등). 코스튬/배지는 NULL 가능
    visual_json TEXT,                             -- 렌더링 힌트 (코스튬: avatar slot/value 등)
    created_at  TEXT NOT NULL
);

-- ----- 회원이 보유한 아이템 -----
CREATE TABLE IF NOT EXISTS user_items (
    user_id     INTEGER NOT NULL,
    item_id     TEXT NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    acquired_at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

-- ----- 회원이 장착한 아이템 (슬롯당 하나) -----
CREATE TABLE IF NOT EXISTS user_equipment (
    user_id     INTEGER NOT NULL,
    slot        TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    equipped_at TEXT NOT NULL,
    PRIMARY KEY (user_id, slot),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

-- ----- (선택) 매물 씨앗 캐시 — 비식별 시장 맥락만 저장 -----
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
);

-- ----- (선택) 카테고리별 집계 트렌드 -----
CREATE TABLE IF NOT EXISTS market_trends (
    id         TEXT PRIMARY KEY,
    category   TEXT,
    trend_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user    ON trade_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_results_user     ON trade_results(user_id);
CREATE INDEX IF NOT EXISTS idx_spawns_user      ON active_spawns(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_items_user  ON user_items(user_id);
CREATE INDEX IF NOT EXISTS idx_seller_inq_user  ON seller_inquiries(user_id, status);
CREATE INDEX IF NOT EXISTS idx_missions_user    ON user_active_missions(user_id, game_role, status);
