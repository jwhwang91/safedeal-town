"""
커뮤니티 피해 사례 MVP (Phase 4/D).

목적: 사용자가 겪은 중고거래/사기 피해 경험을 '비식별 처리 후' 공유해,
      다른 사람의 방어 훈련 자료가 되게 한다. ('나도 비슷했어요' 공감 + 댓글 + 신고)

안전 원칙(하드 룰):
  - 원문(raw)은 절대 저장/반환하지 않는다. 저장 전 redact_sensitive_text 로 민감정보를
    토큰([PHONE][ACCOUNT][URL]...)으로 가리고, 가려진 텍스트만 DB 에 넣는다(raw_body_stored=0).
  - moderation.check_submission 으로 원문을 검사한다:
      reject  → 400 (사유 안내, 저장 안 함)
      pending → 자동 공개 대신 검토 대기(status='pending', 댓글은 'hidden')로 접수
      accept  → 공개(status='approved', 댓글은 'visible')
  - 실명/계좌/연락처/링크 같은 개인정보는 화면·DB 어디에도 원문으로 남기지 않는다.

이 라우터가 만드는 건 '새 파일' 뿐이다. 테이블/설정은 마이그레이션이 이미 만들어 둔다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.analytics import risk_scoring as rs
from app.config import get_settings
from app.database import db_dependency
from app.deps import get_current_user
from app.privacy import moderation
from app.privacy.moderation import SUBMIT_NOTICE
from app.privacy.redactor import redact_sensitive_text

router = APIRouter(prefix="/api/community", tags=["community"])

# 피해 금액 범위(공개 라벨용 코드) — 실제 금액은 받지 않는다.
_LOSS_RANGES = {
    "none", "under_100k", "100k_500k", "500k_1m", "over_1m", "undisclosed",
}
# 목록 필터로 허용하는 상태값 (원문은 어디에도 없으니 상태와 무관하게 안전)
_LIST_STATUSES = {"approved", "pending", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _require_enabled() -> None:
    """기능 게이트: 꺼져 있으면 존재하지 않는 것처럼 404."""
    if not get_settings().community_cases_enabled:
        raise HTTPException(status_code=404, detail="이 기능은 비활성화되어 있어요.")


def _redact(text: str | None) -> tuple[str, list[str]]:
    """한 조각을 비식별화하고 (가린 텍스트, 위험신호 리스트) 를 돌려준다. 실패해도 죽지 않는다."""
    if not text:
        return "", []
    try:
        red, meta = redact_sensitive_text(text)
        return red, list(meta.get("risk_flags") or [])
    except Exception:
        # 최악의 경우에도 원문을 그대로 흘리지 않도록 통째로 가린다.
        return "[내용 확인 필요]", []


# ============================================================
#  요청 모델 (INLINE — 공용 models.py 는 건드리지 않는다)
# ============================================================
class CaseCreate(BaseModel):
    """피해 사례 제출. 세 개의 서술 조각으로 나눠 받아 비식별 후 합친다."""
    title: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)
    platform: str | None = Field(default=None, max_length=40)
    loss_amount_range: str = Field(default="undisclosed", max_length=20)
    incident_date_text: str | None = Field(default=None, max_length=40)
    what_happened: str = Field(min_length=1, max_length=4000)
    what_felt_suspicious: str | None = Field(default=None, max_length=2000)
    what_wish_done: str | None = Field(default=None, max_length=2000)

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v not in rs.ASSESSMENT_CATEGORIES:
            raise ValueError("허용되지 않은 카테고리예요.")
        return v

    @field_validator("loss_amount_range")
    @classmethod
    def _check_loss(cls, v: str) -> str:
        if v not in _LOSS_RANGES:
            raise ValueError("허용되지 않은 피해 금액 범위예요.")
        return v


class CommentCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


class ReactRequest(BaseModel):
    # 현재는 '나도 비슷했어요'(me_too) 하나만 쓰지만, 확장 대비 짧은 키만 허용.
    reaction_type: str = Field(default="me_too", pattern=r"^[a-z0-9_]{1,20}$")


class ReportRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


# ============================================================
#  직렬화 헬퍼 (항상 '가려진' 데이터만 노출)
# ============================================================
def _reaction_count(conn: sqlite3.Connection, case_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM community_case_reactions WHERE case_id = ?",
        (case_id,),
    ).fetchone()
    return int(row["c"]) if row else 0


def _comment_count(conn: sqlite3.Connection, case_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM community_case_comments "
        "WHERE case_id = ? AND status = 'visible'",
        (case_id,),
    ).fetchone()
    return int(row["c"]) if row else 0


def _public_case(row: sqlite3.Row, reaction_count: int, comment_count: int) -> dict:
    """정답지/원문 없는 공개 사례 형태."""
    try:
        signals = json.loads(row["extracted_risk_signals_json"] or "[]")
    except Exception:
        signals = []
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "platform": row["platform"],
        "loss_amount_range": row["loss_amount_range"],
        "incident_date_text": row["incident_date_text"],
        "body": row["redacted_body"],  # 이미 비식별된 본문
        "status": row["status"],
        "risk_signals": signals,
        "reaction_count": reaction_count,
        "comment_count": comment_count,
        "created_at": row["created_at"],
    }


def _get_case_row(conn: sqlite3.Connection, case_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM community_cases WHERE id = ?", (case_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="사례를 찾을 수 없어요.")
    return row


# ============================================================
#  엔드포인트
# ============================================================
@router.get("/cases/notice")
def get_notice(user: sqlite3.Row = Depends(get_current_user)) -> dict:
    """제출 전 사용자에게 보여줄 안내 문구."""
    _require_enabled()
    return {"notice": SUBMIT_NOTICE}


@router.post("/cases")
def create_case(
    body: CaseCreate,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """사례 등록: 원문 검사 → 비식별 → 저장. 반환은 공개(가려진) 사례 + 모더레이션 결과 + 안내."""
    _require_enabled()

    # 1) 원문(합본)으로 모더레이션 판정. 원문은 이 함수 밖으로 절대 나가지 않는다.
    raw_parts = [body.what_happened]
    if body.what_felt_suspicious:
        raw_parts.append(body.what_felt_suspicious)
    if body.what_wish_done:
        raw_parts.append(body.what_wish_done)
    raw_combined = "\n".join(raw_parts)

    mod = moderation.check_submission(raw_combined)
    action = mod.get("action", "pending")
    reasons = mod.get("reasons", [])
    if action == "reject":
        raise HTTPException(
            status_code=400,
            detail={
                "message": "이 내용은 올릴 수 없어요.",
                "reasons": reasons or ["부적절한 내용이 감지되었어요."],
            },
        )
    case_status = "approved" if action == "accept" else "pending"

    # 2) 비식별화: 제목 + 세 서술 조각을 각각 가리고, 한국어 헤더로 합친다.
    flags: list[str] = []
    title_red, tf = _redact(body.title)
    flags.extend(tf)
    if not title_red:
        title_red = "(제목 없음)"

    sections: list[str] = []
    wh_red, f1 = _redact(body.what_happened)
    flags.extend(f1)
    sections.append("[무슨 일이 있었나요]\n" + (wh_red or "(내용 없음)"))

    if body.what_felt_suspicious:
        sus_red, f2 = _redact(body.what_felt_suspicious)
        flags.extend(f2)
        if sus_red:
            sections.append("[무엇이 수상했나요]\n" + sus_red)

    if body.what_wish_done:
        wish_red, f3 = _redact(body.what_wish_done)
        flags.extend(f3)
        if wish_red:
            sections.append("[돌아보니 이렇게 했으면]\n" + wish_red)

    redacted_body = "\n\n".join(sections)

    incident_red, _ = _redact(body.incident_date_text)

    # 위험 신호 중복 제거(순서 보존)
    risk_signals = list(dict.fromkeys(flags))

    # 3) 저장 — raw_body_stored 는 항상 0 (원문 미저장)
    case_id = _new_id()
    now = _now()
    platform = (body.platform or "").strip()[:40] or None
    conn.execute(
        """
        INSERT INTO community_cases
            (id, user_id, title, category, platform, loss_amount_range,
             incident_date_text, redacted_body, raw_body_stored, status,
             labels_json, extracted_risk_signals_json, scenario_candidate_id,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, '[]', ?, NULL, ?, ?)
        """,
        (
            case_id, user["id"], title_red[:80], body.category, platform,
            body.loss_amount_range, (incident_red or None), redacted_body,
            case_status, json.dumps(risk_signals, ensure_ascii=False), now, now,
        ),
    )
    conn.commit()

    row = _get_case_row(conn, case_id)
    public = _public_case(row, 0, 0)

    note = (
        "검토 후 공개돼요. 개인정보가 많이 포함돼 자동 공개 대신 확인 절차를 거칩니다."
        if case_status == "pending"
        else "사례가 공개되었어요. 함께 조심해요!"
    )
    return {
        "case": public,
        "moderation": {
            "action": action,
            "status": case_status,
            "reasons": reasons,
            "message": note,
            "sensitive_hits": mod.get("sensitive_hits", 0),
        },
        "notice": SUBMIT_NOTICE,
    }


@router.get("/cases")
def list_cases(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
    category: str | None = Query(default=None, max_length=40),
    status_filter: str = Query(default="approved", alias="status", max_length=20),
) -> dict:
    """사례 목록 (기본: 공개 승인된 것만, 최신순). 공감/댓글 수 포함. 원문은 절대 반환하지 않는다."""
    _require_enabled()

    status_value = status_filter if status_filter in _LIST_STATUSES else "approved"
    params: list = [status_value]
    where = "status = ?"
    if category and category in rs.ASSESSMENT_CATEGORIES:
        where += " AND category = ?"
        params.append(category)

    rows = conn.execute(
        f"""
        SELECT c.*,
            (SELECT COUNT(*) FROM community_case_reactions r
             WHERE r.case_id = c.id) AS reaction_count,
            (SELECT COUNT(*) FROM community_case_comments cm
             WHERE cm.case_id = c.id AND cm.status = 'visible') AS comment_count
        FROM community_cases c
        WHERE {where}
        ORDER BY c.created_at DESC
        LIMIT 100
        """,
        tuple(params),
    ).fetchall()

    cases = [
        _public_case(r, int(r["reaction_count"] or 0), int(r["comment_count"] or 0))
        for r in rows
    ]
    return {"cases": cases, "count": len(cases), "status": status_value}


@router.get("/cases/{case_id}")
def get_case(
    case_id: str,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """사례 상세 (가려진 본문) + 보이는 댓글 + 공감 수 + 내가 공감했는지 여부."""
    _require_enabled()
    row = _get_case_row(conn, case_id)

    r_count = _reaction_count(conn, case_id)
    c_count = _comment_count(conn, case_id)
    public = _public_case(row, r_count, c_count)

    comment_rows = conn.execute(
        "SELECT id, user_id, redacted_comment, created_at FROM community_case_comments "
        "WHERE case_id = ? AND status = 'visible' ORDER BY created_at ASC",
        (case_id,),
    ).fetchall()
    comments = [
        {
            "id": cr["id"],
            "comment": cr["redacted_comment"],
            "is_mine": cr["user_id"] == user["id"],
            "created_at": cr["created_at"],
        }
        for cr in comment_rows
    ]

    mine = conn.execute(
        "SELECT 1 FROM community_case_reactions WHERE case_id = ? AND user_id = ? LIMIT 1",
        (case_id, user["id"]),
    ).fetchone()

    public["comments"] = comments
    public["user_reacted"] = bool(mine)
    return public


@router.post("/cases/{case_id}/comment")
def add_comment(
    case_id: str,
    body: CommentCreate,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """댓글 등록: 원문 검사 → 비식별 → 저장(visible/hidden). 원문은 저장하지 않는다."""
    _require_enabled()
    _get_case_row(conn, case_id)  # 존재 확인 (404)

    mod = moderation.check_submission(body.comment)
    action = mod.get("action", "pending")
    if action == "reject":
        raise HTTPException(
            status_code=400,
            detail={
                "message": "이 댓글은 올릴 수 없어요.",
                "reasons": mod.get("reasons") or ["부적절한 내용이 감지되었어요."],
            },
        )
    # accept → 바로 노출, pending → 검토 대기(hidden)
    c_status = "visible" if action == "accept" else "hidden"

    red, _flags = _redact(body.comment)
    if not red:
        red = "[내용 확인 필요]"

    comment_id = _new_id()
    now = _now()
    conn.execute(
        "INSERT INTO community_case_comments "
        "(id, case_id, user_id, redacted_comment, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (comment_id, case_id, user["id"], red, c_status, now),
    )
    conn.commit()

    return {
        "comment": {
            "id": comment_id,
            "comment": red,
            "is_mine": True,
            "status": c_status,
            "created_at": now,
        },
        "moderation": {"action": action, "status": c_status,
                       "reasons": mod.get("reasons", [])},
        "comment_count": _comment_count(conn, case_id),
    }


@router.post("/cases/{case_id}/react")
def react_case(
    case_id: str,
    body: ReactRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """공감 토글: 없으면 추가, 있으면 제거 (멱등). UNIQUE 제약으로 중복은 자연 방지."""
    _require_enabled()
    _get_case_row(conn, case_id)  # 존재 확인 (404)

    existing = conn.execute(
        "SELECT id FROM community_case_reactions "
        "WHERE case_id = ? AND user_id = ? AND reaction_type = ?",
        (case_id, user["id"], body.reaction_type),
    ).fetchone()

    if existing:
        conn.execute(
            "DELETE FROM community_case_reactions WHERE id = ?", (existing["id"],)
        )
        reacted = False
    else:
        conn.execute(
            "INSERT OR IGNORE INTO community_case_reactions "
            "(id, case_id, user_id, reaction_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (_new_id(), case_id, user["id"], body.reaction_type, _now()),
        )
        reacted = True
    conn.commit()

    return {
        "case_id": case_id,
        "reaction_type": body.reaction_type,
        "reacted": reacted,
        "reaction_count": _reaction_count(conn, case_id),
    }


@router.post("/cases/{case_id}/report")
def report_case(
    case_id: str,
    body: ReportRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """사례 신고: 신고 사유를 기록(status='open'). 운영자 검토용 큐에 쌓인다."""
    _require_enabled()
    _get_case_row(conn, case_id)  # 존재 확인 (404)

    # 신고 사유도 혹시 모를 개인정보를 가려 저장한다.
    reason_red, _flags = _redact(body.reason)
    conn.execute(
        "INSERT INTO community_case_reports "
        "(id, case_id, user_id, reason, status, created_at) VALUES (?, ?, ?, ?, 'open', ?)",
        (_new_id(), case_id, user["id"], (reason_red or body.reason.strip())[:300], _now()),
    )
    conn.commit()
    return {"ok": True}
