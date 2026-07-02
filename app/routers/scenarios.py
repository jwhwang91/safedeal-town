"""
방어 시나리오 뱅크 라우터 (/api/scenarios).

  GET  /search            : 키워드 검색 (일반 사용자는 approved 만)
  POST /from-case/{id}    : 커뮤니티 사례(비식별) → 방어 시나리오 생성·저장
  GET  /recommend         : 현재 사용자 약점 기반 추천
  POST /{id}/approve      : 시나리오 승인 (데모/관리자 편의)

안전:
  - 응답에 커뮤니티 사례 원문/개인정보는 절대 포함하지 않는다 (public_scenario 형태만).
  - 사례→시나리오는 원문을 복제하지 않고 일반화된 위험 패턴으로 변환한다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.config import get_settings
from app.database import db_dependency
from app.deps import get_current_user
from app.scenarios import generator, retriever, scenario_bank

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------
#  요청/응답 모델 (인라인)
# ------------------------------------------------------------
class ApproveResponse(BaseModel):
    ok: bool
    scenario_id: str


# ============================================================
#  검색
# ============================================================
@router.get("/search")
def search(
    q: str = Query(default="", description="검색어(공백으로 여러 단어 AND)"),
    category: str | None = Query(default=None),
    risk_family: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """키워드 검색. 일반 사용자에게는 approved 시나리오만 노출한다."""
    try:
        results = retriever.search_scenarios(
            conn, q or "",
            category=category, risk_family=risk_family,
            status="approved", limit=limit,
        )
    except Exception:
        results = []
    return {"scenarios": results, "count": len(results)}


# ============================================================
#  추천
# ============================================================
@router.get("/recommend")
def recommend(
    mission_key: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=20),
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 사용자의 약점 차원에 맞춘 approved 시나리오 추천."""
    try:
        results = retriever.recommend_scenarios(
            conn, int(user["id"]),
            active_mission_key=mission_key, limit=limit,
        )
    except Exception:
        results = []
    return {"scenarios": results, "count": len(results)}


# ============================================================
#  사례 → 시나리오 변환
# ============================================================
def _normalize_signals(raw) -> list[str]:
    """extracted_risk_signals_json 을 문자열 리스트로 정규화."""
    out: list[str] = []
    if not raw:
        return out
    try:
        for s in raw:
            if isinstance(s, str):
                out.append(s)
            elif isinstance(s, dict):
                v = s.get("flag") or s.get("signal") or s.get("type") or s.get("key")
                if isinstance(v, str):
                    out.append(v)
    except Exception:
        pass
    return out


@router.post("/from-case/{case_id}")
def from_case(
    case_id: str,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """커뮤니티 사례를 읽어 방어 시나리오로 변환·저장한다.

    응답에는 저장된 공개 시나리오 + {requires_review, provider_used} 만 담는다.
    원문(raw)이나 비식별 본문은 응답에 넣지 않는다.
    """
    s = get_settings()
    # 사례→시나리오 파이프라인은 커뮤니티 사례에 의존하므로 커뮤니티 기능 게이트를 따른다.
    if not s.community_cases_enabled:
        raise HTTPException(status_code=404, detail="이 기능은 비활성화되어 있어요.")

    row = conn.execute(
        "SELECT * FROM community_cases WHERE id = ?", (case_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="해당 사례를 찾을 수 없어요.")

    # 사례 딕트 구성 (비식별 필드만 사용)
    try:
        raw_signals = json.loads(row["extracted_risk_signals_json"] or "[]")
    except Exception:
        raw_signals = []
    case = {
        "title": row["title"],
        "category": row["category"],
        "platform": row["platform"],
        "redacted_body": row["redacted_body"],
        "risk_signals": _normalize_signals(raw_signals),
    }

    # 생성 (template 우선, 검증 필수 — 실패 시 template 폴백)
    try:
        gen = generator.generate_scenario_from_case(conn, case)
    except Exception:
        raise HTTPException(status_code=500, detail="시나리오 생성에 실패했어요.")

    scenario = gen.get("scenario") or {}
    provider_used = gen.get("provider_used", "template")

    # 저장 (검토 게이트에 따라 status 자동 결정)
    try:
        scenario_id = scenario_bank.store_scenario(
            conn, scenario,
            source_type="community_case",
            source_case_id=case_id,
            created_by=f"user:{int(user['id'])}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=500, detail="시나리오 저장에 실패했어요.")

    # 사례에 후보 시나리오 연결 (best-effort — 실패해도 시나리오 저장은 유효)
    try:
        conn.execute(
            "UPDATE community_cases SET scenario_candidate_id = ?, updated_at = ? "
            "WHERE id = ?",
            (scenario_id, _now(), case_id),
        )
    except Exception:
        pass

    conn.commit()

    stored = scenario_bank.get_scenario(conn, scenario_id)
    public = scenario_bank.public_scenario(stored or scenario)
    return {
        "scenario": public,
        "requires_review": bool(gen.get("requires_review", True)),
        "provider_used": provider_used,
    }


# ============================================================
#  승인 (데모/관리자 편의)
# ============================================================
@router.post("/{scenario_id}/approve", response_model=ApproveResponse)
def approve(
    scenario_id: str,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> ApproveResponse:
    """시나리오를 approved 로 승인한다 (데모/관리자 편의)."""
    ok = scenario_bank.approve_scenario(conn, scenario_id)
    if not ok:
        raise HTTPException(status_code=404, detail="해당 시나리오를 찾을 수 없어요.")
    conn.commit()
    return ApproveResponse(ok=True, scenario_id=scenario_id)
