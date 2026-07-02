"""
RAG-lite 검색 (scenario_bank 위에서, 로컬 SQLite 만 사용 — 무거운 의존성 없음).

  - search_scenarios : 키워드 검색 (기본 LIKE 기반, FTS5 가 있으면 시도 후 폴백).
  - recommend_scenarios : 사용자의 '약한 위험 차원' → 위험군 매핑으로 approved 시나리오 추천.

안전:
  - 일반 사용자에게는 status='approved' 만 노출한다 (미승인/커뮤니티 원문은 절대 노출 안 함).
  - 위험 프로필 계층(app.analytics.risk_profile)이 아직 없거나 실패해도
    try/except 로 감싸 '최근 approved' 로 우아하게 폴백한다.
"""
from __future__ import annotations

import sqlite3

from app.scenarios.scenario_bank import public_scenario

# ------------------------------------------------------------
#  검색 대상 필드 (제목/요약/red_flags/카테고리/위험군)
# ------------------------------------------------------------
_SEARCH_EXPR = (
    "(title || ' ' || scenario_summary || ' ' || red_flags_json "
    "|| ' ' || safe_counters_json || ' ' || category || ' ' || risk_family)"
)


# ------------------------------------------------------------
#  위험 차원(dimension) → 시나리오 위험군(risk_family) 매핑
#  (rs.FAMILY_TO_DIMENSION 은 taxonomy 패턴군 기준이라, 시나리오 위험군용 로컬 맵을 둔다)
# ------------------------------------------------------------
_DIMENSION_TO_FAMILIES: dict[str, list[str]] = {
    "price_anomaly_detection": ["off_platform_link", "investment_pressure"],
    "urgency_pressure_resistance": ["voice_call_pressure", "investment_pressure"],
    "off_platform_link_detection": ["off_platform_link", "fake_safe_payment", "job_offer_scam"],
    "prepayment_refusal": ["delivery_payment_risk"],
    "third_party_account_suspicion": ["delivery_payment_risk", "fake_safe_payment"],
    "safe_delivery_trade": ["delivery_payment_risk"],
    "platform_chat_preservation": ["personal_contact_grooming", "off_platform_link"],
    "personal_contact_boundary": ["personal_contact_grooming"],
    "voice_phishing_like_pressure": ["voice_call_pressure", "account_takeover"],
    "romance_scam_boundary": ["romance_boundary_pressure"],
    "refund_villain_response": ["refund_conflict"],
    "seller_misconduct_avoidance": ["refund_conflict"],
    "evidence_based_response": ["delivery_payment_risk"],
    "calm_dispute_handling": ["refund_conflict"],
    "legitimate_claim_recognition": ["refund_conflict"],
}


def _terms(query: str) -> list[str]:
    return [t for t in str(query or "").split() if t.strip()]


# ============================================================
#  검색 (LIKE 기반 + 선택적 FTS5)
# ============================================================
def _search_like(
    conn: sqlite3.Connection,
    query: str,
    category: str | None,
    risk_family: str | None,
    status: str | None,
    limit: int,
) -> list[dict]:
    """LIKE 기반 검색 (파라미터 바인딩 — 주입 안전)."""
    sql = "SELECT * FROM scenario_bank WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if risk_family:
        sql += " AND risk_family = ?"
        params.append(risk_family)
    for term in _terms(query):
        sql += f" AND {_SEARCH_EXPR} LIKE ?"
        params.append(f"%{term}%")
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(int(limit) if limit else 20)

    rows = conn.execute(sql, params).fetchall()
    return [public_scenario(r) for r in rows]


def _fts5_available(conn: sqlite3.Connection) -> bool:
    """이 SQLite 빌드가 FTS5 를 지원하는지 (많은 빌드가 미탑재라 항상 확인)."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS temp.__scn_fts_probe USING fts5(x)"
        )
        conn.execute("DROP TABLE IF EXISTS temp.__scn_fts_probe")
        return True
    except Exception:
        return False


def _try_fts_search(
    conn: sqlite3.Connection,
    query: str,
    category: str | None,
    risk_family: str | None,
    status: str | None,
    limit: int,
) -> list[dict] | None:
    """FTS5 가 가능하면 관련도 순 검색을 시도. 불가/오류면 None (→ LIKE 폴백)."""
    terms = _terms(query)
    if not terms:
        return None
    if not _fts5_available(conn):
        return None

    tmp = "temp.__scn_fts_search"
    try:
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        conn.execute(
            f"CREATE VIRTUAL TABLE {tmp} USING fts5(sid UNINDEXED, body)"
        )
        base_sql = f"SELECT id AS sid, {_SEARCH_EXPR} AS body FROM scenario_bank WHERE 1=1"
        base_params: list = []
        if status:
            base_sql += " AND status = ?"
            base_params.append(status)
        if category:
            base_sql += " AND category = ?"
            base_params.append(category)
        if risk_family:
            base_sql += " AND risk_family = ?"
            base_params.append(risk_family)

        candidates = conn.execute(base_sql, base_params).fetchall()
        if not candidates:
            conn.execute(f"DROP TABLE IF EXISTS {tmp}")
            return []
        for row in candidates:
            conn.execute(
                f"INSERT INTO __scn_fts_search(sid, body) VALUES (?, ?)",
                (row["sid"], row["body"] or ""),
            )

        # 각 term 을 큰따옴표로 감싸 MATCH 구문 오류를 피하고 암묵 AND 로 결합
        match_expr = " ".join('"' + t.replace('"', "") + '"' for t in terms)
        matched = conn.execute(
            "SELECT sid FROM __scn_fts_search WHERE __scn_fts_search MATCH ? "
            "ORDER BY rank LIMIT ?",
            (match_expr, int(limit) if limit else 20),
        ).fetchall()
        ids = [m["sid"] for m in matched]
        conn.execute(f"DROP TABLE IF EXISTS {tmp}")

        if not ids:
            return []
        # 관련도 순서를 보존하며 원본 행을 가져온다
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT * FROM scenario_bank WHERE id IN ({placeholders})", ids
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        ordered = [by_id[i] for i in ids if i in by_id]
        return [public_scenario(r) for r in ordered]
    except Exception:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tmp}")
        except Exception:
            pass
        return None


def search_scenarios(
    conn: sqlite3.Connection,
    query: str = "",
    *,
    category: str | None = None,
    risk_family: str | None = None,
    status: str | None = "approved",
    limit: int = 20,
) -> list[dict]:
    """scenario_bank 키워드 검색 → 공개 시나리오 리스트.

    설계:
      - LIKE 를 '기본(primary)' 경로로 삼는다. 한국어 부분일치 재현율(recall)이
        가장 중요하기 때문이다 (예: '택배'가 '택배거래' 안에 있어도 매칭돼야 한다).
        FTS5 unicode61 토크나이저는 CJK 를 통째 토큰화해 부분일치를 놓치므로,
        FTS 결과가 LIKE 결과를 '대체'하게 두지 않는다.
      - FTS5 가 있으면 '관련도 순 재정렬' 보너스로만 쓴다 (있으면 앞으로, 없으면 그대로).
        따라서 FTS5 유무와 무관하게 재현율은 항상 LIKE 수준으로 보장된다.
      - query 가 비면 필터만 적용해 최근 순으로 돌려준다.
    """
    like_results = _search_like(conn, query, category, risk_family, status, limit)
    if not _terms(query) or len(like_results) <= 1:
        return like_results

    # 있으면 FTS5 관련도 순서를 LIKE 결과 위에 얹는다 (재현율은 그대로 유지)
    try:
        fts = _try_fts_search(conn, query, category, risk_family, status, limit)
        if fts:
            order = {s.get("id"): i for i, s in enumerate(fts)}
            like_results.sort(key=lambda s: order.get(s.get("id"), 10 ** 9))
    except Exception:
        pass
    return like_results


# ============================================================
#  추천 (약한 위험 차원 → 위험군)
# ============================================================
def _weak_dimensions(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """사용자의 약한 위험 차원 키 목록. 프로필 계층이 없으면 빈 리스트."""
    try:
        from app.analytics import risk_profile  # Phase C 계층 (없을 수 있음)

        prof = risk_profile.build_user_risk_profile(conn, user_id)
        if not isinstance(prof, dict):
            return []
        weak = prof.get("weak_dimensions")
        if isinstance(weak, list) and weak:
            return [str(k) for k in weak]
        # 대안 형태: dimensions 리스트에서 level=='weak' 추출
        dims = prof.get("dimensions") or []
        out: list[str] = []
        if isinstance(dims, list):
            for d in dims:
                if isinstance(d, dict) and d.get("level") == "weak":
                    key = d.get("key") or d.get("dimension")
                    if key:
                        out.append(str(key))
        return out
    except Exception:
        return []


def recommend_scenarios(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    active_mission_key: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """사용자의 약한 차원에 맞춘 approved 시나리오 추천.

    - 약한 차원 → 위험군 매핑으로 매칭되는 approved 시나리오를 우선 채운다.
    - active_mission_key 가 있으면 해당 미션의 차원을 앞쪽으로 편향한다.
    - 데이터가 부족하면 최근 approved 로 우아하게 채운다.
    - 절대 미승인/커뮤니티 원문 시나리오를 돌려주지 않는다.
    """
    limit = int(limit) if limit else 5

    # 타깃 위험군 수집 (순서 = 우선순위)
    target_families: list[str] = []

    # 1) 활성 미션 차원 편향
    if active_mission_key:
        try:
            from app.analytics import risk_scoring as rs

            dim = rs.dimension_for_mission(active_mission_key)
            if dim:
                for fam in _DIMENSION_TO_FAMILIES.get(dim, []):
                    if fam not in target_families:
                        target_families.append(fam)
        except Exception:
            pass

    # 2) 약한 차원 → 위험군
    for dim in _weak_dimensions(conn, user_id):
        for fam in _DIMENSION_TO_FAMILIES.get(dim, []):
            if fam not in target_families:
                target_families.append(fam)

    picked: list[dict] = []
    seen_ids: set = set()

    def _add(rows: list[dict]) -> None:
        for r in rows:
            rid = r.get("id")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            picked.append(r)
            if len(picked) >= limit:
                break

    # 타깃 위험군별로 approved 시나리오를 모은다
    for fam in target_families:
        if len(picked) >= limit:
            break
        try:
            rows = _search_like(conn, "", None, fam, "approved", limit)
            _add(rows)
        except Exception:
            continue

    # 부족하면 최근 approved 로 채운다 (폴백)
    if len(picked) < limit:
        try:
            fillers = _search_like(conn, "", None, None, "approved", limit * 3)
            _add(fillers)
        except Exception:
            pass

    return picked[:limit]
