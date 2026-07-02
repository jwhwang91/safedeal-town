"""
진단 채점 로직 (전부 규칙 기반 — LLM 은 채점에 관여하지 않는다).

역할:
  - score_answer      : 한 문항의 답을 채점 (정오/점수/측정 차원 반환).
  - finalize_session  : 세션의 모든 답을 모아 차원별·전체 점수를 계산하고,
                        user_assessment_sessions 에 결과(JSON)를 기록한다.
  - build_session_result : 이미 완료된 세션 row → 클라이언트용 결과 dict.

점수 관례(risk_scoring 과 동일): 0~100, 높을수록 방어 역량이 강함.
공유 계약(SHARED DATA CONTRACT)에 맞춰 dimension_scores_json / summary_json 을 채운다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.analytics import risk_scoring as rs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(row_or_dict) -> dict:
    if row_or_dict is None:
        return {}
    if isinstance(row_or_dict, dict):
        return dict(row_or_dict)
    try:
        return {k: row_or_dict[k] for k in row_or_dict.keys()}
    except Exception:
        return dict(row_or_dict)


def _normalize_keys(values) -> list[str]:
    """보기 키 리스트를 소문자·공백제거로 정규화."""
    out: list[str] = []
    if isinstance(values, (list, tuple)):
        for v in values:
            if v is None:
                continue
            s = str(v).strip().lower()
            if s:
                out.append(s)
    return out


def _selected_keys(answer: dict) -> list[str]:
    """사용자 답 {"key":"b"} 또는 {"keys":["b"]} → 정규화된 키 리스트."""
    if not isinstance(answer, dict):
        return []
    if answer.get("keys"):
        return _normalize_keys(answer.get("keys"))
    k = answer.get("key")
    if k is not None and str(k).strip():
        return [str(k).strip().lower()]
    return []


def _correct_keys(question: dict) -> list[str]:
    """문항의 정답 키 리스트를 안전하게 파싱."""
    raw = question.get("correct_answer_json")
    data: dict = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    return _normalize_keys(data.get("correct_keys", []))


# ------------------------------------------------------------
#  단일 문항 채점
# ------------------------------------------------------------
def score_answer(question: dict, answer: dict) -> dict:
    """한 문항의 답을 채점한다.

    반환: {"is_correct","score_delta","detected_dimensions","explanation","correct_keys"}
    detected_dimensions 는 항상 그 문항이 측정하는 차원(risk_family) 1개 —
    정오와 무관하게 '이 차원을 측정했다'는 사실을 세션 집계에 넘긴다.
    """
    q = _as_dict(question)
    correct = _correct_keys(q)
    selected = _selected_keys(answer)

    is_correct = bool(correct) and set(selected) == set(correct)
    dim = q.get("risk_family")
    detected = [dim] if dim else []

    return {
        "is_correct": is_correct,
        "score_delta": 1 if is_correct else 0,
        "detected_dimensions": detected,
        "explanation": q.get("explanation") or "",
        "correct_keys": correct,
    }


# ------------------------------------------------------------
#  세션 마감 → 차원/전체 점수 계산 + 저장
# ------------------------------------------------------------
def _recommended_modules(weak_keys: list[str]) -> list[str]:
    """약한 차원의 추천 훈련 문구를 모아 추천 모듈 리스트로 만든다."""
    mods: list[str] = []
    seen: set[str] = set()
    for key in weak_keys:
        meta = rs.dimension_meta(key)
        rec = (meta.get("recommended_training") or "").strip()
        if rec and rec not in seen:
            seen.add(rec)
            mods.append(rec)
    if not mods:
        mods.append(
            "전반적으로 방어 습관이 안정적이에요. 다양한 시나리오로 꾸준히 훈련을 이어가세요."
        )
    return mods


def finalize_session(conn: sqlite3.Connection, session_row) -> dict:
    """세션의 모든 답을 모아 점수를 확정하고 세션 row 에 기록한다(멱등하게 덮어씀).

    반환: build_session_result 형태의 클라이언트용 전체 결과 dict.
    """
    d = _as_dict(session_row)
    session_id = d.get("id")

    rows = conn.execute(
        "SELECT * FROM user_assessment_answers WHERE session_id = ?",
        (session_id,),
    ).fetchall()

    dim_agg: dict[str, dict] = {}  # dimension_key -> {"correct":int,"total":int}
    total_correct = 0
    total_answered = 0

    for r in rows:
        total_answered += 1
        is_correct = int(r["is_correct"] or 0)
        if is_correct:
            total_correct += 1
        try:
            dims = json.loads(r["detected_dimensions_json"] or "[]")
        except Exception:
            dims = []
        for dim in dims:
            if not dim:
                continue
            agg = dim_agg.setdefault(dim, {"correct": 0, "total": 0})
            agg["total"] += 1
            if is_correct:
                agg["correct"] += 1

    dim_scores: dict[str, dict] = {}
    strengths: list[str] = []
    weaknesses: list[str] = []
    for key, agg in dim_agg.items():
        score = rs.ratio_to_score(agg["correct"], agg["total"])
        dim_scores[key] = {
            "correct": agg["correct"],
            "total": agg["total"],
            "score": score,
        }
        if agg["total"] > 0:
            if score >= 75:
                strengths.append(key)
            elif score < 40:
                weaknesses.append(key)

    overall = rs.ratio_to_score(total_correct, total_answered)
    recommended = _recommended_modules(weaknesses)

    # /start 에서 저장한 selected_ids 는 보존한다.
    try:
        prev_summary = json.loads(d.get("summary_json") or "{}")
    except Exception:
        prev_summary = {}

    summary = {
        "assessment_type": d.get("assessment_type"),
        "total_questions": total_answered,
        "correct_count": total_correct,
        "selected_ids": prev_summary.get("selected_ids", []),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_modules": recommended,
    }

    now = _now()
    conn.execute(
        """
        UPDATE user_assessment_sessions
        SET status = 'completed', completed_at = ?, score = ?,
            dimension_scores_json = ?, summary_json = ?
        WHERE id = ?
        """,
        (
            now,
            overall,
            json.dumps(dim_scores, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False),
            session_id,
        ),
    )
    conn.commit()

    updated = conn.execute(
        "SELECT * FROM user_assessment_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return build_session_result(updated or d)


def build_session_result(session_row) -> dict:
    """완료된 세션 row → 클라이언트용 결과 dict (계약 형태).

    /complete, /latest 가 공통으로 쓴다. 차원 점수는 약한 순으로 정렬해 준다.
    """
    d = _as_dict(session_row)

    try:
        dim_scores = json.loads(d.get("dimension_scores_json") or "{}")
    except Exception:
        dim_scores = {}
    try:
        summary = json.loads(d.get("summary_json") or "{}")
    except Exception:
        summary = {}

    dimension_list: list[dict] = []
    for key, v in dim_scores.items():
        meta = rs.dimension_meta(key)
        try:
            score = int(v.get("score", 0))
        except Exception:
            score = 0
        level = rs.level_for_score(score)
        dimension_list.append({
            "key": key,
            "label": meta.get("label", key),
            "score": score,
            "level": level,
            "level_label": rs.level_label_ko(level),
            "correct": int(v.get("correct", 0) or 0),
            "total": int(v.get("total", 0) or 0),
        })
    dimension_list.sort(key=lambda x: (x["score"], x["key"]))

    strengths = [rs.dimension_meta(k).get("label", k) for k in summary.get("strengths", [])]
    weaknesses = [rs.dimension_meta(k).get("label", k) for k in summary.get("weaknesses", [])]

    try:
        overall = int(d.get("score") or 0)
    except Exception:
        overall = 0

    return {
        "session_id": d.get("id"),
        "assessment_type": d.get("assessment_type") or summary.get("assessment_type"),
        "status": d.get("status"),
        "score": overall,
        "dimension_scores": dimension_list,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_modules": summary.get("recommended_modules", []),
        "total_questions": summary.get("total_questions", 0),
        "correct_count": summary.get("correct_count", 0),
        "started_at": d.get("started_at"),
        "completed_at": d.get("completed_at"),
        "disclaimer": rs.DISCLAIMER,
    }
