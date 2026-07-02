"""
기관/코호트 데모 대시보드 라우터 (Phase 10/G).

학교·복지관·지자체·금융기관 같은 '기관'이 방어 훈련을 단체로 도입한다고 가정한 데모.
한 코호트(학습자 묶음)의 훈련 성과를 '집계 지표'로만 보여준다.

⚠️ 프라이버시 원칙(하드 규칙):
  - 이 라우터는 절대 개인의 대화 원문/커뮤니티 사례 원문/개별 채팅 내용을 노출하지 않는다.
  - 오직 '집계(aggregate) 숫자'만 계산한다. 누가 무엇을 틀렸는지 개인 단위로 드러내지 않는다.
  - 점수는 방어 훈련용 데모 지표이며, 공식 진단이 아니다 (rs.DISCLAIMER 항상 첨부).

기능 게이트: get_settings().org_demo_dashboard_enabled 가 꺼져 있으면 모든 엔드포인트 404.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.analytics import risk_scoring as rs
from app.config import get_settings
from app.database import db_dependency
from app.deps import get_current_user

router = APIRouter(prefix="/api/orgs", tags=["orgs"])

# 기관 유형(데모): 학교 / 복지관 / 지자체 / 금융기관 / 기타
_ORG_TYPES = {"school", "senior_center", "local_gov", "financial", "other"}

# 집계 카드에서 '약함/강함' 차원을 몇 개까지 보여줄지
_TOP_DIMENSIONS = 4


# ------------------------------------------------------------
#  요청 모델 (인라인)
# ------------------------------------------------------------
class CreateDemoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    org_type: str = Field(default="other")


class AddCurrentUserRequest(BaseModel):
    cohort_id: str | None = None


# ------------------------------------------------------------
#  게이트 / 공통 헬퍼
# ------------------------------------------------------------
def _require_enabled() -> None:
    """기능 플래그가 꺼져 있으면 404 로 감춘다."""
    if not get_settings().org_demo_dashboard_enabled:
        raise HTTPException(status_code=404, detail="이 기능은 비활성화되어 있어요.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(text: str | None, default):
    """TEXT 컬럼의 JSON 을 안전하게 파싱 (실패해도 크래시 금지)."""
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _cohort_member_count(conn: sqlite3.Connection, cohort_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cohort_members WHERE cohort_id = ?", (cohort_id,)
    ).fetchone()
    return int(row["n"]) if row else 0


def _next_alias(conn: sqlite3.Connection, cohort_id: str) -> str:
    """코호트 내 다음 학습자 별칭 (예: '학습자-3'). 개인 신원은 별칭으로만 표기한다."""
    return f"학습자-{_cohort_member_count(conn, cohort_id) + 1}"


def _recent_cohort_id_for_user(conn: sqlite3.Connection, user_id: int) -> str | None:
    """사용자가 소속된 가장 최근(코호트 생성 기준) 데모 코호트 id. 없으면 None."""
    row = conn.execute(
        """
        SELECT c.id AS cohort_id
        FROM cohort_members m
        JOIN cohorts c ON c.id = m.cohort_id
        WHERE m.user_id = ?
        ORDER BY c.created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return row["cohort_id"] if row else None


def _resolve_cohort(
    conn: sqlite3.Connection, user_id: int, cohort_id: str | None
) -> sqlite3.Row:
    """cohort_id 가 주어지면 그 코호트, 없으면 사용자의 최근 코호트. 못 찾으면 404."""
    if cohort_id:
        row = conn.execute(
            "SELECT * FROM cohorts WHERE id = ?", (cohort_id,)
        ).fetchone()
    else:
        rid = _recent_cohort_id_for_user(conn, user_id)
        row = (
            conn.execute("SELECT * FROM cohorts WHERE id = ?", (rid,)).fetchone()
            if rid
            else None
        )
    if not row:
        raise HTTPException(status_code=404, detail="코호트를 찾을 수 없어요.")
    return row


def _member_user_ids(conn: sqlite3.Connection, cohort_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT user_id FROM cohort_members WHERE cohort_id = ?", (cohort_id,)
    ).fetchall()
    return [int(r["user_id"]) for r in rows]


def _placeholders(n: int) -> str:
    return ",".join(["?"] * n)


def _avg_int(values: list[float]) -> int:
    """빈 리스트면 0, 아니면 반올림 정수 평균."""
    if not values:
        return 0
    return int(round(sum(values) / len(values)))


# ------------------------------------------------------------
#  진단 세션 조회 (집계용)
# ------------------------------------------------------------
def _latest_completed_score(
    conn: sqlite3.Connection, user_id: int, assessment_type: str
) -> int | None:
    """해당 유형의 '완료된' 가장 최근 진단 점수(0~100). 없으면 None."""
    row = conn.execute(
        """
        SELECT score
        FROM user_assessment_sessions
        WHERE user_id = ? AND assessment_type = ? AND status = 'completed'
          AND score IS NOT NULL
        ORDER BY completed_at DESC, started_at DESC
        LIMIT 1
        """,
        (user_id, assessment_type),
    ).fetchone()
    if not row or row["score"] is None:
        return None
    return int(row["score"])


def _latest_completed_dimensions(
    conn: sqlite3.Connection, user_id: int
) -> dict:
    """유형 무관, 가장 최근 완료 진단의 dimension_scores_json (없으면 빈 dict)."""
    row = conn.execute(
        """
        SELECT dimension_scores_json
        FROM user_assessment_sessions
        WHERE user_id = ? AND status = 'completed'
        ORDER BY completed_at DESC, started_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return {}
    data = _loads(row["dimension_scores_json"], {})
    return data if isinstance(data, dict) else {}


# ------------------------------------------------------------
#  집계 지표 계산
# ------------------------------------------------------------
def _score_cards(conn: sqlite3.Connection, member_ids: list[int]) -> dict:
    """기준(baseline)/최근(post_training→fallback baseline) 평균 점수와 향상도."""
    baseline_scores: list[float] = []
    latest_scores: list[float] = []
    for uid in member_ids:
        base = _latest_completed_score(conn, uid, "baseline")
        post = _latest_completed_score(conn, uid, "post_training")
        if base is not None:
            baseline_scores.append(base)
        latest = post if post is not None else base
        if latest is not None:
            latest_scores.append(latest)
    avg_baseline = _avg_int(baseline_scores)
    avg_latest = _avg_int(latest_scores)
    # 향상도: 기준 데이터가 아예 없으면 오해를 줄이려 0 으로 둔다.
    improvement = (avg_latest - avg_baseline) if baseline_scores else 0
    return {
        "avg_baseline_score": avg_baseline,
        "avg_latest_score": avg_latest,
        "avg_improvement": improvement,
        "baseline_sample_size": len(baseline_scores),
        "latest_sample_size": len(latest_scores),
    }


def _dimension_cards(conn: sqlite3.Connection, member_ids: list[int]) -> dict:
    """멤버들의 최근 진단 차원 점수를 차원별로 평균 → 약함/강함 카드."""
    # dimension_key -> [scores]
    buckets: dict[str, list[float]] = {}
    for uid in member_ids:
        dims = _latest_completed_dimensions(conn, uid)
        for key, val in dims.items():
            if not isinstance(val, dict):
                continue
            score = val.get("score")
            if score is None:
                continue
            try:
                buckets.setdefault(key, []).append(float(score))
            except (TypeError, ValueError):
                continue

    scored: list[dict] = []
    for key, vals in buckets.items():
        avg = _avg_int(vals)
        meta = rs.dimension_meta(key)
        level = rs.level_for_score(avg)
        scored.append(
            {
                "key": key,
                "label": meta.get("label", key),
                "avg_score": avg,
                "level": level,
                "level_label": rs.level_label_ko(level),
                "sample_size": len(vals),
            }
        )

    weakest = sorted(scored, key=lambda d: d["avg_score"])[:_TOP_DIMENSIONS]
    strongest = sorted(scored, key=lambda d: d["avg_score"], reverse=True)[
        :_TOP_DIMENSIONS
    ]
    return {"weakest": weakest, "strongest": strongest, "all_measured": scored}


def _mission_completion_rate(conn: sqlite3.Connection, member_ids: list[int]) -> dict:
    """코호트 전체의 미션 완료율: completed / (completed + failed)."""
    if not member_ids:
        return {"completed": 0, "failed": 0, "rate": 0.0}
    ph = _placeholders(len(member_ids))
    rows = conn.execute(
        f"""
        SELECT status, COUNT(*) AS n
        FROM user_active_missions
        WHERE user_id IN ({ph})
        GROUP BY status
        """,
        member_ids,
    ).fetchall()
    counts = {r["status"]: int(r["n"]) for r in rows}
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    denom = completed + failed
    rate = round(completed / denom, 3) if denom > 0 else 0.0
    return {"completed": completed, "failed": failed, "rate": rate}


def _scenario_categories_trained(
    conn: sqlite3.Connection, member_ids: list[int]
) -> list[str]:
    """훈련된 시나리오 카테고리(집계). 우선 거래 세션 카테고리, 없으면 진단 카테고리."""
    if not member_ids:
        return []
    ph = _placeholders(len(member_ids))
    cats: list[str] = []
    # 1) 거래 결과 ↔ 세션 조인에서 item_category (best-effort)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT s.item_category AS cat
            FROM trade_results r
            JOIN trade_sessions s ON s.id = r.session_id
            WHERE r.user_id IN ({ph}) AND s.item_category IS NOT NULL
            """,
            member_ids,
        ).fetchall()
        cats = [r["cat"] for r in rows if r["cat"]]
    except Exception:
        cats = []
    # 2) 폴백: 진단에서 다룬 카테고리
    if not cats:
        try:
            rows = conn.execute(
                f"""
                SELECT DISTINCT qb.category AS cat
                FROM user_assessment_answers a
                JOIN assessment_question_bank qb ON qb.id = a.question_id
                WHERE a.user_id IN ({ph}) AND qb.category IS NOT NULL
                """,
                member_ids,
            ).fetchall()
            cats = [r["cat"] for r in rows if r["cat"]]
        except Exception:
            cats = []
    # 순서 안정 + 중복 제거
    seen: set[str] = set()
    out: list[str] = []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _recommended_curriculum(weakest: list[dict]) -> list[str]:
    """약한 차원 → 추천 훈련 문구(한국어). 중복 제거."""
    out: list[str] = []
    seen: set[str] = set()
    for d in weakest:
        meta = rs.dimension_meta(d.get("key", ""))
        tip = (meta.get("recommended_training") or "").strip()
        if tip and tip not in seen:
            seen.add(tip)
            out.append(tip)
    return out


# ------------------------------------------------------------
#  엔드포인트
# ------------------------------------------------------------
@router.post("/demo/create")
def create_demo(
    body: CreateDemoRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """데모 기관 + 기본 코호트 생성 후, 현재 사용자를 첫 학습자로 등록한다."""
    _require_enabled()

    org_type = body.org_type if body.org_type in _ORG_TYPES else "other"
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="기관 이름을 입력해 주세요.")

    now = _now()
    org_id = str(uuid.uuid4())
    cohort_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO organizations (id, name, org_type, created_at) VALUES (?, ?, ?, ?)",
        (org_id, name, org_type, now),
    )
    conn.execute(
        """
        INSERT INTO cohorts (id, organization_id, name, description, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (cohort_id, org_id, "기본 코호트", "데모용 기본 학습자 그룹", now),
    )
    # 현재 사용자를 첫 멤버로 (별칭은 신원 대신 익명 표기)
    alias = _next_alias(conn, cohort_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO cohort_members
            (id, cohort_id, user_id, display_alias, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), cohort_id, user["id"], alias, now),
    )
    conn.commit()

    return {
        "organization": {
            "id": org_id,
            "name": name,
            "org_type": org_type,
            "created_at": now,
        },
        "cohort": {
            "id": cohort_id,
            "organization_id": org_id,
            "name": "기본 코호트",
            "member_count": _cohort_member_count(conn, cohort_id),
            "created_at": now,
        },
    }


@router.post("/demo/cohort/add-current-user")
def add_current_user(
    body: AddCurrentUserRequest,
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 사용자를 코호트에 (멱등) 등록한다. cohort_id 생략 시 최근 코호트."""
    _require_enabled()

    cohort = _resolve_cohort(conn, user["id"], body.cohort_id)
    cohort_id = cohort["id"]

    alias = _next_alias(conn, cohort_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO cohort_members
            (id, cohort_id, user_id, display_alias, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), cohort_id, user["id"], alias, _now()),
    )
    conn.commit()

    return {
        "ok": True,
        "cohort_id": cohort_id,
        "member_count": _cohort_member_count(conn, cohort_id),
    }


@router.get("/demo/dashboard")
def demo_dashboard(
    cohort_id: str | None = Query(default=None),
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """코호트의 집계 지표 대시보드. 개인 원문/대화 내용은 절대 노출하지 않는다."""
    _require_enabled()

    cohort = _resolve_cohort(conn, user["id"], cohort_id)
    cid = cohort["id"]
    org = conn.execute(
        "SELECT * FROM organizations WHERE id = ?", (cohort["organization_id"],)
    ).fetchone()

    member_ids = _member_user_ids(conn, cid)
    member_count = len(member_ids)

    # 빈 코호트도 에러 대신 0 으로 우아하게 처리
    scores = _score_cards(conn, member_ids)
    dims = _dimension_cards(conn, member_ids)
    missions = _mission_completion_rate(conn, member_ids)
    categories = _scenario_categories_trained(conn, member_ids)
    curriculum = _recommended_curriculum(dims["weakest"])

    total_signals = (
        scores["baseline_sample_size"]
        + scores["latest_sample_size"]
        + missions["completed"]
        + missions["failed"]
        + len(dims["all_measured"])
    )

    return {
        "cohort": {
            "id": cid,
            "name": cohort["name"],
            "organization_id": cohort["organization_id"],
        },
        "organization": (
            {
                "id": org["id"],
                "name": org["name"],
                "org_type": org["org_type"],
            }
            if org
            else None
        ),
        "cards": {
            "member_count": member_count,
            "avg_baseline_score": scores["avg_baseline_score"],
            "avg_latest_score": scores["avg_latest_score"],
            "avg_improvement": scores["avg_improvement"],
            "weakest_dimensions": dims["weakest"],
            "strongest_dimensions": dims["strongest"],
            "mission_completion_rate": missions["rate"],
            "mission_counts": {
                "completed": missions["completed"],
                "failed": missions["failed"],
            },
            "scenario_categories_trained": categories,
            "recommended_next_curriculum": curriculum,
        },
        "confidence": rs.confidence_from_evidence(total_signals),
        "note": (
            "이 대시보드는 코호트 '집계' 지표만 보여줘요. 개인의 대화 원문이나 "
            "개별 사례 내용은 포함되지 않으며, 데모용 지표입니다."
        ),
        "disclaimer": rs.DISCLAIMER,
    }


@router.get("/demo/list")
def demo_list(
    user: sqlite3.Row = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict:
    """현재 사용자가 소속된 데모 기관/코호트 목록 (id, 이름, 유형, 멤버 수)."""
    _require_enabled()

    # 사용자가 멤버로 속한 코호트 → 그 코호트가 속한 기관
    rows = conn.execute(
        """
        SELECT DISTINCT c.organization_id AS org_id
        FROM cohort_members m
        JOIN cohorts c ON c.id = m.cohort_id
        WHERE m.user_id = ?
        """,
        (user["id"],),
    ).fetchall()
    org_ids = [r["org_id"] for r in rows]

    organizations: list[dict] = []
    for org_id in org_ids:
        org = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        if not org:
            continue
        cohort_rows = conn.execute(
            "SELECT * FROM cohorts WHERE organization_id = ? ORDER BY created_at DESC",
            (org_id,),
        ).fetchall()
        cohorts = [
            {
                "id": cr["id"],
                "name": cr["name"],
                "member_count": _cohort_member_count(conn, cr["id"]),
                "created_at": cr["created_at"],
            }
            for cr in cohort_rows
        ]
        organizations.append(
            {
                "id": org["id"],
                "name": org["name"],
                "org_type": org["org_type"],
                "created_at": org["created_at"],
                "cohort_count": len(cohorts),
                "cohorts": cohorts,
            }
        )

    return {"organizations": organizations, "count": len(organizations)}
