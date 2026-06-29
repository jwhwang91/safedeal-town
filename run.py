"""
실행 스크립트.  터미널에서  python run.py  하면 서버가 뜨고,
브라우저가 자동으로 앱 메인 화면(index.html)으로 열린다.

서버가 뜨면:
  - 내 PC:        http://localhost:8000
  - 같은 와이파이의 다른 기기/외부:  http://<내 IP>:8000
    (HOST=0.0.0.0 이라 외부 접속 허용. 공유기 포트포워딩/방화벽은 README 참고)

초기화 옵션:
  python run.py                # 평소 실행 (데이터 보존)
  python run.py --reset-maps   # 저장된 동네 맵/스폰만 비움 → 다음 접속 때 새로 생성
                               #   (계정/전적 유지. 위치 기반 동네를 새 규칙으로 다시 그리고 싶을 때)
  python run.py --reset        # 앱 전체 초기화: DB 파일 삭제 → NPC 재시드
                               #   (⚠️ 계정/전적까지 전부 삭제, 완전 새 출발)
  python run.py --no-browser   # 브라우저 자동 열기 끄기

참고: '네모난 옛 맵' 이 보이는 건 보통 서버가 아니라 '브라우저 캐시'다.
      자동으로 열리는 탭은 캐시를 우회하도록 URL 에 ?fresh= 를 붙여 연다.
      이미 열어둔 탭이라면 시크릿창으로 열거나 강력 새로고침(Cmd/Ctrl+Shift+R) 할 것.
"""
from __future__ import annotations

import argparse
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from app.config import get_settings


def _reset_maps(db_path) -> None:
    """저장된 동네 맵/스폰만 비운다 (계정/전적 보존). 다음 접속 때 새로 생성된다."""
    if not db_path.exists():
        print("  [reset-maps] DB 가 아직 없어 비울 것이 없음 (새로 생성될 예정).")
        return
    conn = sqlite3.connect(db_path)
    try:
        cleared = []
        for table in ("active_spawns", "map_profiles"):
            try:
                n = conn.execute(f"DELETE FROM {table}").rowcount
                cleared.append(f"{table}={n}")
            except sqlite3.OperationalError:
                pass  # 아직 없는 테이블이면 무시
        conn.commit()
        print(f"  [reset-maps] 동네 맵/스폰 비움 ({', '.join(cleared) or '없음'}). 계정/전적은 유지.")
    finally:
        conn.close()


def _reset_all(db_path) -> None:
    """앱 전체 초기화: DB 파일(및 WAL/SHM)을 삭제한다. 시작 시 스키마+NPC 가 새로 생성된다."""
    removed = []
    for suffix in ("", "-wal", "-shm"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            p.unlink()
            removed.append(p.name)
    print(f"  [reset] 전체 초기화 — 삭제: {', '.join(removed) or '없음'}. "
          "시작 시 NPC 가 다시 시드됩니다 (계정/전적 전부 사라짐).")


def _port_in_use(host: str, port: int) -> bool:
    """이미 무언가 이 포트를 듣고 있나? (옛 서버가 떠 있으면 옛 파일을 서빙해 혼란을 줌)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def _open_browser_when_ready(url: str, health_url: str, timeout: float = 15.0) -> None:
    """서버가 실제로 응답할 때까지 기다렸다가 브라우저로 메인 화면을 연다.

    고정 sleep 대신 health 엔드포인트를 폴링해서, 서버가 준비되자마자 연다.
    혹시 준비 확인에 실패해도 마지막에 한 번은 그냥 열어 본다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1) as resp:
                if resp.status == 200:
                    break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    webbrowser.open(url)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="중고타운(SafeDeal Town) 실행기")
    parser.add_argument("--reset-maps", action="store_true",
                        help="저장된 동네 맵/스폰만 비움 (계정/전적 유지)")
    parser.add_argument("--reset", action="store_true",
                        help="앱 전체 초기화: DB 삭제 후 NPC 재시드 (계정/전적 전부 삭제)")
    parser.add_argument("--no-browser", action="store_true",
                        help="브라우저 자동 열기 끄기")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    settings = get_settings()
    db_path = settings.database_path

    # 초기화 옵션 처리 (서버 시작 전에 수행). --reset 이 --reset-maps 보다 우선.
    if args.reset:
        _reset_all(db_path)
    elif args.reset_maps:
        _reset_maps(db_path)

    # 이미 같은 포트를 듣고 있으면, 옛 서버가 옛 정적파일을 서빙해 '네모난 맵' 처럼
    # 보일 수 있다. 새 서버가 바인딩에 실패하기 전에 먼저 알려준다.
    if _port_in_use(settings.host, settings.port):
        print(f"  [경고] 이미 무언가 {settings.port} 포트를 사용 중입니다. "
              f"옛 서버가 떠 있을 수 있어요.\n"
              f"         먼저 종료하세요:  lsof -ti:{settings.port} | xargs kill -9   "
              f"(Windows: netstat -ano | findstr :{settings.port})")

    # 외부 바인딩은 0.0.0.0 이지만, 브라우저는 localhost 로 연다.
    # 자동으로 여는 탭은 ?fresh= 로 브라우저 HTTP 캐시를 우회 → 항상 최신 빌드를 받는다.
    cache_bust = int(time.time())
    main_url = f"http://localhost:{settings.port}/?fresh={cache_bust}"
    health_url = f"http://localhost:{settings.port}/api/health"

    # 서버는 uvicorn.run() 이 블로킹하므로, 브라우저 열기는 별도 스레드에서.
    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(main_url, health_url),
            daemon=True,
        ).start()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
