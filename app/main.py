"""
SafeDeal Town - 애플리케이션 진입점.

FastAPI 앱을 만들고:
  - 시작 시 DB 초기화 + NPC 시드
  - /api/* 라우터(인증/게임/채팅) 연결
  - / 에서 static 폴더의 게임 클라이언트(index.html) 서빙

실행:  python run.py   (또는  uvicorn app.main:app --host 0.0.0.0 --port 8000)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import initialize_database
from app.routers import assessment, auth, chat, community, game, orgs, report, scenarios

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 앱이 켜질 때 한 번: 테이블 만들고 NPC 채워넣기
    initialize_database()
    s = get_settings()
    mode = {
        "openai": "OpenAI API (실시간 GPT)",
        "local_claude": "local_claude (로컬 CLI, 실패 시 mock 폴백)",
        "mock": "mock (내장 시나리오)",
    }.get(s.ai_provider, "mock (내장 시나리오)")
    print(f"  [SafeDeal Town] AI 모드: {mode}")
    print(f"  [SafeDeal Town] 맵 제공자: {s.map_provider_effective}")
    print(f"  [SafeDeal Town] 접속 주소: http://localhost:{s.port}")
    yield


app = FastAPI(title="SafeDeal Town", version="1.0.0", lifespan=lifespan)


# ------------------------------------------------------------
#  캐시 정책 (지난 세션 최대 혼란 포인트: 옛 JS/CSS 가 캐시돼서
#  "셋업 없음 + 네모난 단순 맵 + 스폰 없음" 으로 보이던 함정 방지)
#
#  - 정적 JS/CSS 는 항상 재검증(no-cache)하게 한다. 파일이 바뀌면
#    StaticFiles 가 주는 ETag 가 바뀌어 브라우저가 새 파일을 받는다.
#    (index.html 의 ?v= 와 더불어 이중 안전장치)
# ------------------------------------------------------------
@app.middleware("http")
async def _no_stale_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") and path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


app.include_router(auth.router)
app.include_router(game.router)
app.include_router(chat.router)
# 방어 훈련 플랫폼 레이어 (진단 / 리포트 / 커뮤니티 / 시나리오 뱅크 / 기관 데모)
app.include_router(assessment.router)
app.include_router(report.router)
app.include_router(community.router)
app.include_router(scenarios.router)
app.include_router(orgs.router)


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "ai_mode": s.ai_provider,
        "map_provider": s.map_provider_effective,
    }


# 게임 클라이언트
@app.get("/")
def index() -> FileResponse:
    # index.html 은 절대 캐시하지 않는다(no-store). 그래야 안에 박힌 ?v= 가
    # 항상 최신이라 옛 JS/CSS 캐시를 확실히 무효화한다. (브라우저가 옛 index.html
    # 자체를 캐시해서 옛 스크립트를 계속 쓰던 함정을 원천 차단)
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
