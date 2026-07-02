"""
개인 리포트 라우터 (prefix /api/report).

통합 위험 프로필 위에 얹는 '투명 리포트' API. 모든 점수는 방어 훈련용 데모 지표이며
의료/법률/공식 진단이 아니다. 각 핸들러는 실패해도 데모가 멈추지 않도록 try/except 로
안전한 최소 응답으로 우아하게 폴백한다(500 을 내지 않는다).
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app.analytics import report_builder
from app.analytics import risk_scoring as rs
from app.database import db_dependency
from app.deps import get_current_user

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/personal")
def personal(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 훈련 점수 + 강/약점 + 추천 미션 + 점수 설명."""
    try:
        return report_builder.build_personal_report(conn, int(user["id"]))
    except Exception:
        return {
            "current_training_score": 0,
            "confidence": "demo_low",
            "strongest_skills": [],
            "weakest_skills": [],
            "recommended_next_missions": [],
            "recommended_next_actions": [
                "아직 리포트를 만들 훈련 기록이 부족해요. 진단과 미션을 먼저 진행해 보세요.",
            ],
            "score_explanation": [],
            "risk_profile": {
                "overall_risk_score": 0,
                "confidence": "demo_low",
                "risk_dimensions": [],
                "strengths": [],
                "weaknesses": [],
                "recommended_next_actions": [],
                "disclaimer": rs.DISCLAIMER,
                "is_demo": True,
            },
            "disclaimer": rs.DISCLAIMER,
            "is_demo": True,
        }


@router.get("/before-after")
def before_after(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """baseline vs post_training 향상도 비교."""
    try:
        return report_builder.build_before_after(conn, int(user["id"]))
    except Exception:
        return {
            "available": False,
            "message": "향상도 비교를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
            "have_baseline": False,
            "have_post": False,
        }


@router.get("/evidence")
def evidence(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """진단/미션/거래 집계와 차원별 근거 (투명성, 집계·비식별만)."""
    try:
        return report_builder.build_evidence(conn, int(user["id"]))
    except Exception:
        return {
            "assessment_sessions": [],
            "mission_counts": {"completed": 0, "failed": 0, "skipped": 0, "active": 0},
            "trade_verdict_counts": {},
            "dimension_evidence": [],
            "confidence": "demo_low",
            "note": "원문 대화(transcript)는 포함하지 않으며, 집계·비식별 지표만 제공합니다.",
            "disclaimer": rs.DISCLAIMER,
            "is_demo": True,
        }
