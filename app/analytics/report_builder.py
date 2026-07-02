"""
개인 리포트 빌더 (통합 프로필 위에 얹는 '투명 리포트' 레이어).

⚠️ 모든 점수는 방어 훈련용 데모 지표다(의료/법률/공식 진단 아님).
리포트는 '왜 이 점수인지'를 집계·비식별 근거로 설명한다. 원문 대화(transcript)는 절대 노출하지 않는다.

세 가지 리포트:
  - build_personal_report : 현재 훈련 점수 + 강점/약점 + 추천 미션 + 점수 설명 불릿
  - build_before_after     : baseline vs post_training 향상도 비교
  - build_evidence         : 진단/미션/거래 집계와 차원별 근거 묶음 (투명성)
"""
from __future__ import annotations

import json
import sqlite3

from app.analytics import risk_profile
from app.analytics import risk_scoring as rs
from app.analytics.risk_profile import _mission_title  # 근거 문구용 미션 제목

# 택배거래 훈련 미션 (통과율 설명에 사용)
_DELIVERY_MISSION_KEYS = ("delivery_only_buyer", "delivery_safe_seller")


def _safe_json(text, default):
    """TEXT 컬럼의 JSON 을 안전하게 파싱한다."""
    try:
        val = json.loads(text) if text else default
        return val if val is not None else default
    except (ValueError, TypeError):
        return default


def _latest_completed_session(conn: sqlite3.Connection, user_id: int,
                              assessment_type: str) -> sqlite3.Row | None:
    """해당 유형의 '가장 최근 완료' 진단 세션 한 개."""
    return conn.execute(
        "SELECT * FROM user_assessment_sessions "
        "WHERE user_id = ? AND assessment_type = ? AND status = 'completed' "
        "ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 1",
        (user_id, assessment_type),
    ).fetchone()


def _recommended_missions_for_weak(risk_dimensions: list[dict]) -> list[dict]:
    """약한/보통 차원의 훈련 미션을 라벨 중심으로 추천한다 (중복 제거)."""
    out: list[dict] = []
    seen: set[str] = set()
    for d in risk_dimensions:  # weak→strong 정렬됨
        if d.get("level") == "strong":
            continue
        meta = rs.dimension_meta(d["key"])
        for k in (meta.get("mission_keys") or []):
            if k in seen:
                continue
            seen.add(k)
            out.append({
                "mission_key": k,
                "title": _mission_title(k),
                "dimension_label": d["label"],
            })
    return out[:5]


# ------------------------------------------------------------
#  개인 리포트
# ------------------------------------------------------------
def _score_explanation(conn: sqlite3.Connection, user_id: int, profile: dict) -> list[str]:
    """점수 근거를 사람이 읽는 불릿으로 풀어 쓴다 (최근 거래/진단 집계 기반)."""
    bullets: list[str] = []
    dim_map = {d["key"]: d for d in profile.get("risk_dimensions", [])}

    # 최근 거래 8건의 최종 판단 정답률
    try:
        rows = conn.execute(
            "SELECT correct FROM trade_results WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT 8",
            (user_id,),
        ).fetchall()
        if rows:
            total = len(rows)
            correct = sum(1 for r in rows if int(r["correct"] or 0) == 1)
            bullets.append(f"최근 훈련 거래 {total}건 중 {correct}건에서 최종 판단이 정확했어요.")
    except Exception:
        pass

    # 외부 링크 유도 감지율 (차원 점수)
    off = dim_map.get("off_platform_link_detection")
    if off and off.get("score") is not None:
        bullets.append(f"외부 링크 유도를 알아채는 감지율은 약 {off['score']}% 수준이에요.")

    # 택배거래 미션 통과율
    try:
        placeholders = ", ".join("?" for _ in _DELIVERY_MISSION_KEYS)
        drow = conn.execute(
            f"SELECT status, COUNT(*) AS c FROM user_active_missions "
            f"WHERE user_id = ? AND mission_key IN ({placeholders}) "
            f"AND status IN ('completed', 'failed') GROUP BY status",
            (user_id, *_DELIVERY_MISSION_KEYS),
        ).fetchall()
        dcounts = {r["status"]: int(r["c"]) for r in drow}
        dcompleted = dcounts.get("completed", 0)
        dtotal = dcompleted + dcounts.get("failed", 0)
        if dtotal > 0:
            rate = rs.ratio_to_score(dcompleted, dtotal)
            bullets.append(f"택배거래 미션 통과율은 {dcompleted}/{dtotal} (약 {rate}%)이에요.")
    except Exception:
        pass

    # 기본 진단에서 약하게 나온 영역
    try:
        base = _latest_completed_session(conn, user_id, "baseline")
        if base is not None:
            summary = _safe_json(base["summary_json"], {})
            weak = summary.get("weaknesses") or []
            if weak:
                labels = [rs.dimension_meta(k)["label"] for k in weak][:4]
                bullets.append("기본 진단에서 약하게 나온 영역: " + ", ".join(labels) + ".")
    except Exception:
        pass

    if not bullets:
        bullets.append("아직 훈련 기록이 적어요. 진단과 미션을 진행하면 점수 설명이 더 구체화됩니다.")
    return bullets


def build_personal_report(conn: sqlite3.Connection, user_id: int) -> dict:
    """통합 프로필 + 현재 훈련 점수 + 강/약점 + 추천 미션 + 점수 설명 불릿."""
    profile = risk_profile.build_user_risk_profile(conn, user_id)
    dims = profile.get("risk_dimensions", [])

    recommended_missions: list[dict] = []
    explanation: list[str] = []
    try:
        recommended_missions = _recommended_missions_for_weak(dims)
    except Exception:
        pass
    try:
        explanation = _score_explanation(conn, user_id, profile)
    except Exception:
        explanation = []

    return {
        "current_training_score": profile.get("overall_risk_score", 0),
        "confidence": profile.get("confidence"),
        "strongest_skills": profile.get("strengths", []),
        "weakest_skills": profile.get("weaknesses", []),
        "recommended_next_missions": recommended_missions,
        "recommended_next_actions": profile.get("recommended_next_actions", []),
        "score_explanation": explanation,
        "risk_profile": profile,
        "disclaimer": rs.DISCLAIMER,
        "is_demo": True,
    }


# ------------------------------------------------------------
#  Before / After (baseline vs post_training)
# ------------------------------------------------------------
def _next_step_after(improvement: int, dim_improvements: list[dict]) -> str:
    """향상도 비교 후 다음 단계 한 줄 제안."""
    if dim_improvements:
        worst = min(dim_improvements, key=lambda d: d["post_score"])
        if worst["post_score"] < 75:
            meta = rs.dimension_meta(worst["key"])
            train = meta.get("recommended_training", "")
            return (
                f"다음 목표는 '{worst['label']}'예요 (현재 {worst['post_score']}점). "
                f"{train}".strip()
            )
    if improvement > 0:
        return "향상 흐름이 좋아요. 새로운 유형의 시나리오로 훈련 범위를 넓혀 보세요."
    return "훈련 후 진단을 한 번 더 진행해 향상도를 확인해 보세요."


def build_before_after(conn: sqlite3.Connection, user_id: int) -> dict:
    """baseline·post_training 이 모두 완료됐을 때 향상도를 비교한다."""
    baseline = _latest_completed_session(conn, user_id, "baseline")
    post = _latest_completed_session(conn, user_id, "post_training")
    have_baseline = baseline is not None
    have_post = post is not None

    if not (have_baseline and have_post):
        missing: list[str] = []
        if not have_baseline:
            missing.append("기본 진단(baseline)")
        if not have_post:
            missing.append("훈련 후 진단(post_training)")
        return {
            "available": False,
            "message": " · ".join(missing) + "을(를) 먼저 완료하면 향상도를 비교해 드려요.",
            "have_baseline": have_baseline,
            "have_post": have_post,
        }

    b_score = int(baseline["score"] or 0)
    p_score = int(post["score"] or 0)
    b_dims = _safe_json(baseline["dimension_scores_json"], {})
    p_dims = _safe_json(post["dimension_scores_json"], {})

    dim_improvements: list[dict] = []
    for key in rs.DIMENSION_KEYS:
        b_entry = b_dims.get(key) if isinstance(b_dims, dict) else None
        p_entry = p_dims.get(key) if isinstance(p_dims, dict) else None
        if not (isinstance(b_entry, dict) and isinstance(p_entry, dict)):
            continue
        bs = int(b_entry.get("score", 0) or 0)
        ps = int(p_entry.get("score", 0) or 0)
        dim_improvements.append({
            "key": key,
            "label": rs.dimension_meta(key)["label"],
            "baseline_score": bs,
            "post_score": ps,
            "delta": ps - bs,
        })
    dim_improvements.sort(key=lambda d: d["delta"], reverse=True)

    improvement = p_score - b_score
    return {
        "available": True,
        "baseline_score": b_score,
        "post_score": p_score,
        "improvement": improvement,
        "dimension_improvements": dim_improvements,
        "recommended_next_step": _next_step_after(improvement, dim_improvements),
        "disclaimer": rs.DISCLAIMER,
        "is_demo": True,
    }


# ------------------------------------------------------------
#  근거 묶음 (투명성 — 집계/비식별만)
# ------------------------------------------------------------
def build_evidence(conn: sqlite3.Connection, user_id: int) -> dict:
    """진단 세션 요약 + 미션 성공/실패 수 + 거래 판정 집계 + 차원별 근거."""
    profile = risk_profile.build_user_risk_profile(conn, user_id)

    # 완료된 진단 세션 요약 (원문/정답키 없음)
    sessions: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT assessment_type, score, completed_at, summary_json "
            "FROM user_assessment_sessions WHERE user_id = ? AND status = 'completed' "
            "ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 10",
            (user_id,),
        ).fetchall()
        for r in rows:
            summary = _safe_json(r["summary_json"], {})
            sessions.append({
                "assessment_type": r["assessment_type"],
                "score": int(r["score"]) if r["score"] is not None else None,
                "completed_at": r["completed_at"],
                "total_questions": summary.get("total_questions"),
                "correct_count": summary.get("correct_count"),
            })
    except Exception:
        pass

    # 미션 성공/실패 집계
    mission_counts = {"completed": 0, "failed": 0, "skipped": 0, "active": 0}
    try:
        mrows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM user_active_missions "
            "WHERE user_id = ? GROUP BY status",
            (user_id,),
        ).fetchall()
        for r in mrows:
            if r["status"] in mission_counts:
                mission_counts[r["status"]] = int(r["c"])
    except Exception:
        pass

    # 거래 판정 집계 (원문 대화 없음, 라벨별 개수만)
    verdict_counts: dict[str, int] = {}
    try:
        vrows = conn.execute(
            "SELECT verdict, COUNT(*) AS c FROM trade_results WHERE user_id = ? GROUP BY verdict",
            (user_id,),
        ).fetchall()
        verdict_counts = {r["verdict"]: int(r["c"]) for r in vrows}
    except Exception:
        pass

    # 프로필의 차원별 근거 (왜 이 점수인지)
    dimension_evidence = [
        {
            "key": d["key"],
            "label": d["label"],
            "score": d["score"],
            "level_label": d.get("level_label"),
            "evidence": d.get("evidence", []),
        }
        for d in profile.get("risk_dimensions", [])
    ]

    return {
        "assessment_sessions": sessions,
        "mission_counts": mission_counts,
        "trade_verdict_counts": verdict_counts,
        "dimension_evidence": dimension_evidence,
        "confidence": profile.get("confidence"),
        "note": "원문 대화(transcript)는 포함하지 않으며, 집계·비식별 지표만 제공합니다.",
        "disclaimer": rs.DISCLAIMER,
        "is_demo": True,
    }
