"""
DB 연결 관리.
SQLite 파일 하나를 쓰고, FastAPI 의존성으로 커넥션을 꺼내 쓴다.
앱이 켜질 때 schema.sql 을 실행해 테이블을 만들고, NPC 시드를 넣는다.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from app.config import get_settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """row 를 dict 처럼 쓸 수 있는 커넥션을 연다.

    동시성: FastAPI 가 sync 라우터를 스레드풀에서 돌리므로 요청마다 별도 커넥션이
    동시에 DB 를 쓴다(예: 6초마다 도는 /spawns 폴링 + /world + 거래 종료). 기본
    rollback 저널은 '쓰기 1개'만 허용해 충돌 시 'database is locked' 가 났다.
      - WAL 모드: 읽기는 쓰기를 막지 않고, 쓰기 1개는 직렬화된다 (락 경합 급감).
      - busy_timeout: 잠겨 있으면 즉시 실패하지 말고 최대 N초 기다렸다 재시도한다.
    """
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout(초) → busy_timeout 으로도 반영된다. 락 대기를 넉넉히 준다.
    conn = sqlite3.connect(settings.database_path, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 15000;")  # 잠김 시 15초까지 대기 후 재시도
    conn.execute("PRAGMA journal_mode = WAL;")     # 동시 읽기/쓰기 허용 (DB 단위로 지속)
    conn.execute("PRAGMA synchronous = NORMAL;")   # WAL 과 함께 안전하면서 더 빠름
    return conn


def db_dependency() -> Iterator[sqlite3.Connection]:
    """FastAPI Depends 용. 요청 하나당 커넥션 하나, 끝나면 닫는다."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def initialize_database() -> None:
    """테이블 생성 + 마이그레이션 + NPC 시드. 앱 시작 시 한 번 호출된다."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
        # 순환 import 방지를 위해 여기서 늦게 import
        from app.migrations import run_migrations
        from app.seed import seed_npcs

        # 기존 DB 에 빠진 컬럼/테이블을 멱등하게 채운다 (데이터 보존)
        run_migrations(conn)
        seed_npcs(conn)
        conn.commit()
    finally:
        conn.close()
