"""
사기 취약도 진단 라우터 (baseline / post_training / quick_check).

흐름:
  POST /start    → 세션 생성(문항 선택·순서 고정) + 첫 문항
  POST /answer   → 기대되는 다음 문항에만 답 제출 → 즉시 채점 + 다음 문항
  POST /complete → 세션 마감(차원/전체 점수 확정) + 전체 결과
  GET  /latest   → 가장 최근 완료 세션 결과(타입별/전체)
  GET  /history  → 내 진단 세션 목록(최신순)

원칙:
  - 채점은 전부 규칙 기반(scoring). 정답은 /start·/answer 의 문항 payload 로 절대 새지 않는다.
  - 세션 소유권·진행 상태·문항 순서를 서버가 강제한다(클라이언트 신뢰 금지).
  - 어떤 조회/집계 실패도 요청 전체를 무너뜨리지 않게 방어적으로 처리한다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.assessment import question_bank as qbank
from app.assessment import scoring
from app.database import db_dependency
from app.deps import get_current_user

router = APIRouter(prefix="/api/assessment", tags=["assessment"])

_ALLOWED_TYPES = {"baseline", "post_training", "quick_check"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ------------------------------------------------------------
#  요청 모델 (인라인)
# ------------------------------------------------------------
class StartRequest(BaseModel):
    assessment_type: str = Field(default="baseline", max_length=32)


class AnswerPayload(BaseModel):
    key: str | None = Field(default=None, max_length=8)
    keys: list[str] | None = Field(default=None, max_length=8)


class AnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    question_id: str = Field(min_length=1, max_length=80)
    answer: AnswerPayload = Field(default_factory=AnswerPayload)


class CompleteRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


# ------------------------------------------------------------
#  내부 헬퍼
# ------------------------------------------------------------
def _load_owned_session(conn: sqlite3.Connection, session_id: str, user_id: int) -> sqlite3.Row:
    """세션을 불러오되, 내 것이 아니거나 없으면 404."""
    row = conn.execute(
        "SELECT * FROM user_assessment_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row or int(row["user_id"]) != int(user_id):
        raise HTTPException(status_code=404, detail="진단 세션을 찾을 수 없어요.")
    return row


def _selected_ids(session_row: sqlite3.Row) -> list[str]:
    try:
        summary = json.loads(session_row["summary_json"] or "{}")
    except Exception:
        summary = {}
    ids = summary.get("selected_ids") or []
    return [str(i) for i in ids if i]


# ------------------------------------------------------------
#  POST /start
# ------------------------------------------------------------
@router.post("/start")
def start(
    body: StartRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    assessment_type = (body.assessment_type or "baseline").strip()
    if assessment_type not in _ALLOWED_TYPES:
        assessment_type = "baseline"

    selected_ids = qbank.select_question_ids(conn, assessment_type)
    if not selected_ids:
        raise HTTPException(status_code=500, detail="진단 문항이 아직 준비되지 않았어요.")

    session_id = _new_id()
    now = _now()
    summary = {
        "assessment_type": assessment_type,
        "selected_ids": selected_ids,
        "total_questions": len(selected_ids),
    }
    conn.execute(
        """
        INSERT INTO user_assessment_sessions
            (id, user_id, assessment_type, status, started_at,
             dimension_scores_json, summary_json)
        VALUES (?, ?, ?, 'in_progress', ?, '{}', ?)
        """,
        (session_id, int(user["id"]), assessment_type, now,
         json.dumps(summary, ensure_ascii=False)),
    )
    conn.commit()

    first = qbank.get_question(conn, selected_ids[0])
    return {
        "session_id": session_id,
        "assessment_type": assessment_type,
        "total_questions": len(selected_ids),
        "index": 0,
        "question": qbank.public_question(first) if first else None,
    }


# ------------------------------------------------------------
#  POST /answer
# ------------------------------------------------------------
@router.post("/answer")
def answer(
    body: AnswerRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    session_row = _load_owned_session(conn, body.session_id, int(user["id"]))
    if session_row["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="이미 종료된 진단 세션이에요.")

    selected_ids = _selected_ids(session_row)
    if not selected_ids:
        raise HTTPException(status_code=500, detail="진단 세션 문항 정보를 읽을 수 없어요.")

    answered = conn.execute(
        "SELECT question_id FROM user_assessment_answers WHERE session_id = ?",
        (body.session_id,),
    ).fetchall()
    answered_ids = {r["question_id"] for r in answered}
    answered_count = len(answered)

    if body.question_id in answered_ids:
        raise HTTPException(status_code=409, detail="이미 답한 문항이에요.")
    if answered_count >= len(selected_ids):
        raise HTTPException(status_code=409, detail="모든 문항에 답했어요. 결과를 확인해 주세요.")

    expected_id = selected_ids[answered_count]
    if body.question_id != expected_id:
        raise HTTPException(status_code=409, detail="순서에 맞지 않는 문항이에요.")

    question = qbank.get_question(conn, body.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="문항을 찾을 수 없어요.")

    answer_dict = body.answer.model_dump(exclude_none=True)
    result = scoring.score_answer(question, answer_dict)

    conn.execute(
        """
        INSERT INTO user_assessment_answers
            (id, session_id, user_id, question_id, answer_json,
             is_correct, score_delta, detected_dimensions_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _new_id(),
            body.session_id,
            int(user["id"]),
            body.question_id,
            json.dumps(answer_dict, ensure_ascii=False),
            1 if result["is_correct"] else 0,
            int(result["score_delta"]),
            json.dumps(result["detected_dimensions"], ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()

    next_index = answered_count + 1
    done = next_index >= len(selected_ids)
    next_question = None
    if not done:
        nq = qbank.get_question(conn, selected_ids[next_index])
        next_question = qbank.public_question(nq) if nq else None

    return {
        "is_correct": result["is_correct"],
        "correct_keys": result["correct_keys"],
        "explanation": result["explanation"],
        "score_delta": result["score_delta"],
        "index": answered_count,
        "next_index": next_index,
        "question": next_question,
        "done": done,
    }


# ------------------------------------------------------------
#  POST /complete
# ------------------------------------------------------------
@router.post("/complete")
def complete(
    body: CompleteRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    session_row = _load_owned_session(conn, body.session_id, int(user["id"]))

    if session_row["status"] == "completed":
        return scoring.build_session_result(session_row)

    return scoring.finalize_session(conn, session_row)


# ------------------------------------------------------------
#  GET /latest
# ------------------------------------------------------------
@router.get("/latest")
def latest(
    assessment_type: str | None = Query(default=None, max_length=32),
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict | None:
    atype = (assessment_type or "").strip()
    if atype and atype in _ALLOWED_TYPES:
        row = conn.execute(
            """
            SELECT * FROM user_assessment_sessions
            WHERE user_id = ? AND assessment_type = ? AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (int(user["id"]), atype),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM user_assessment_sessions
            WHERE user_id = ? AND status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """,
            (int(user["id"]),),
        ).fetchone()

    if not row:
        return None
    return scoring.build_session_result(row)


# ------------------------------------------------------------
#  GET /history
# ------------------------------------------------------------
@router.get("/history")
def history(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, assessment_type, score, started_at, completed_at, status
        FROM user_assessment_sessions
        WHERE user_id = ?
        ORDER BY started_at DESC
        LIMIT 100
        """,
        (int(user["id"]),),
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        out.append({
            "session_id": r["id"],
            "assessment_type": r["assessment_type"],
            "score": r["score"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "status": r["status"],
        })
    return out
