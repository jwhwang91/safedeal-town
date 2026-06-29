"""
NPC 시드.

personas.py 에 정의된 NPC(판매자 + 구매자)들을 npcs 테이블에 넣는다.
앱이 켜질 때마다 호출되지만, 이미 들어있는 NPC 는 최신 데이터로 '업데이트만' 한다.

중요:
  예전엔 INSERT OR REPLACE 를 썼는데, 이는 같은 PK 행을 '삭제 후 재삽입' 한다.
  npcs.id 를 참조하는 trade_sessions / trade_results / player_npc_progress 에
  ON DELETE CASCADE 가 걸려 있어, 잘못하면 연관된 거래 기록까지 날아갈 수 있다.
  그래서 안전한 SQLite UPSERT(ON CONFLICT ... DO UPDATE)로 바꿨다.
  이러면 행을 지우지 않고 컬럼 값만 갱신해서 관련 기록이 보존된다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.ai.personas import ALL_NPCS


def seed_npcs(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for npc in ALL_NPCS:
        conn.execute(
            """
            INSERT INTO npcs
                (id, name, item_name, item_category, listing_price, market_price,
                 location, role, difficulty, persona_json, tactics_json,
                 sprite_color, spawn_x, spawn_y, npc_kind, visual_theme,
                 category, spawn_behavior_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name           = excluded.name,
                item_name      = excluded.item_name,
                item_category  = excluded.item_category,
                listing_price  = excluded.listing_price,
                market_price   = excluded.market_price,
                location       = excluded.location,
                role           = excluded.role,
                difficulty     = excluded.difficulty,
                persona_json   = excluded.persona_json,
                tactics_json   = excluded.tactics_json,
                sprite_color   = excluded.sprite_color,
                spawn_x        = excluded.spawn_x,
                spawn_y        = excluded.spawn_y,
                npc_kind       = excluded.npc_kind,
                visual_theme   = excluded.visual_theme,
                category       = excluded.category,
                spawn_behavior_json = excluded.spawn_behavior_json
            """,
            (
                npc["id"],
                npc["name"],
                npc["item_name"],
                npc["item_category"],
                npc["listing_price"],
                npc["market_price"],
                npc["location"],
                npc["role"],
                npc["difficulty"],
                json.dumps(npc["persona"], ensure_ascii=False),
                json.dumps(npc["tactics"], ensure_ascii=False),
                npc["sprite_color"],
                npc["spawn_x"],
                npc["spawn_y"],
                npc.get("npc_kind", "seller"),
                npc.get("visual_theme"),
                npc.get("category"),
                json.dumps(npc.get("spawn_behavior"), ensure_ascii=False)
                if npc.get("spawn_behavior") is not None
                else None,
                now,
            ),
        )
