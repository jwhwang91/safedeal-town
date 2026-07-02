"""
통합 위험 프로필(unified risk profile) 빌더.

⚠️ 이 모듈은 '사기를 더 잘하는 법'이 아니라, 사용자가 '어떤 위험 신호에 약한지'를
투명하게 통합해 방어 훈련을 개인화하기 위한 점수만 만든다. 의료/법률/공식 진단이 아니다.

네 갈래 근거를 rs.DIMENSION_KEYS(15개 차원) 위에 0~100 점수(높을수록 안전/강함)로 환산해
가중 평균으로 블렌딩한다:
  (a) 최근 완료 진단(assessment) — dimension_scores_json (post_training 우선)
  (b) 게임 숙련도(gameplay mastery) — pattern_family → 차원 매핑
  (c) 미션 성공/실패(missions) — 완료는 가점, 실패는 감점
  (d) 부정행위(misconduct) — trade_results.verdict == 'player_misconduct'

근거가 하나도 없는 차원은 score=None / level='unknown' 으로 두고 전체 평균에서 제외한다.
각 차원의 evidence 는 '왜 이 점수인지'를 사람이 읽을 수 있는 한국어로 설명한다(투명성).
"""
from __future__ import annotations

import json
import sqlite3

from app.ai import adaptive_selector
from app.analytics import risk_scoring as rs

# 소스별 블렌딩 가중치 (진단·미션·부정행위는 직접 신호라 무겁게, 게임 숙련도는 보조)
_W_ASSESSMENT = 1.0
_W_GAMEPLAY = 0.8
_W_MISSION = 1.0
_W_MISCONDUCT = 1.2

# 미션/부정행위를 0~100 점수로 환산하는 기준값
_MISSION_PASS_SCORE = 88
_MISSION_FAIL_SCORE = 25
_MISCONDUCT_SCORE = 18

# 진단 유형 라벨 (근거 문구용)
_ASSESSMENT_TYPE_KO = {
    "baseline": "기본 진단",
    "post_training": "훈련 후 진단",
}


def _safe_json(text, default):
    """TEXT 컬럼의 JSON 을 안전하게 파싱한다. 실패하면 default."""
    try:
        val = json.loads(text) if text else default
        return val if val is not None else default
    except (ValueError, TypeError):
        return default


def _mission_title(mission_key: str) -> str:
    """미션 키 → 사람이 읽는 제목. 알 수 없으면 키 그대로(근거 문구용)."""
    try:
        from app import missions as _m
        entry = getattr(_m, "_CATALOG_BY_KEY", {}).get(mission_key)
        if entry and entry.get("title"):
            return str(entry["title"])
    except Exception:
        pass
    return mission_key


def _add(acc: dict, dim: str | None, score: float, weight: float, evidence: str) -> None:
    """차원 누적기에 (점수, 가중치, 근거문구) 기여를 하나 더한다."""
    if not dim:
        return
    acc.setdefault(dim, []).append((float(score), float(weight), str(evidence)))


# ------------------------------------------------------------
#  (a) 진단 근거
# ------------------------------------------------------------
def _collect_assessment_evidence(conn: sqlite3.Connection, user_id: int,
                                 acc: dict) -> tuple[int, bool]:
    """완료된 진단에서 차원별 점수를 모은다. 같은 차원은 post_training 을 우선한다."""
    rows = conn.execute(
        "SELECT assessment_type, completed_at, started_at, dimension_scores_json "
        "FROM user_assessment_sessions WHERE user_id = ? AND status = 'completed' "
        "ORDER BY COALESCE(completed_at, started_at) DESC",
        (user_id,),
    ).fetchall()
    if not rows:
        return 0, False

    # 유형별 '가장 최근' 세션만 남긴다 (rows 는 최신순).
    latest_by_type: dict[str, sqlite3.Row] = {}
    for r in rows:
        t = r["assessment_type"]
        if t not in latest_by_type:
            latest_by_type[t] = r

    # post_training → baseline → 기타 순으로 우선순위를 준다.
    priority = {"post_training": 0, "baseline": 1}
    ordered = sorted(latest_by_type.items(), key=lambda kv: priority.get(kv[0], 2))

    signals = 0
    for key in rs.DIMENSION_KEYS:
        for atype, row in ordered:
            dims = _safe_json(row["dimension_scores_json"], {})
            entry = dims.get(key) if isinstance(dims, dict) else None
            if not isinstance(entry, dict):
                continue
            correct = int(entry.get("correct", 0) or 0)
            total = int(entry.get("total", 0) or 0)
            score = entry.get("score")
            if score is None:
                score = rs.ratio_to_score(correct, total)
            type_ko = _ASSESSMENT_TYPE_KO.get(atype, atype)
            label = rs.dimension_meta(key)["label"]
            _add(
                acc, key, score, _W_ASSESSMENT,
                f"{type_ko}에서 '{label}' 문항 {total}개 중 {correct}개 정답 (점수 {int(score)})",
            )
            signals += max(total, 1)
            break  # 이 차원은 우선순위 높은 세션 하나만 사용
    return signals, True


# ------------------------------------------------------------
#  (b) 게임 숙련도 근거
# ------------------------------------------------------------
def _collect_gameplay_evidence(conn: sqlite3.Connection, user_id: int,
                               acc: dict) -> int:
    """구매자/판매자 훈련 숙련도를 pattern_family → 차원으로 환산한다."""
    signals = 0
    for role in ("buyer", "seller"):
        try:
            prof = adaptive_selector.get_user_training_profile(conn, user_id, role)
        except Exception:
            continue
        role_ko = "구매자" if role == "buyer" else "판매자"
        for card in (prof.get("mastery_by_pattern") or {}).values():
            seen = int(card.get("times_seen", 0) or 0)
            if seen <= 0:
                continue
            dim = rs.dimension_for_family(card.get("pattern_family"))
            if not dim:
                continue
            pct = int(card.get("mastery_pct", 0) or 0)
            _add(
                acc, dim, pct, _W_GAMEPLAY,
                f"{role_ko} 훈련: '{card.get('label')}' 숙련도 {pct}% ({seen}회 훈련)",
            )
            signals += seen
    return signals


# ------------------------------------------------------------
#  (c) 미션 근거
# ------------------------------------------------------------
def _collect_mission_evidence(conn: sqlite3.Connection, user_id: int,
                              acc: dict) -> int:
    """완료/실패 미션을 차원 가/감점으로 반영한다."""
    rows = conn.execute(
        "SELECT mission_key, status FROM user_active_missions "
        "WHERE user_id = ? AND status IN ('completed', 'failed')",
        (user_id,),
    ).fetchall()
    signals = 0
    for r in rows:
        dim = rs.dimension_for_mission(r["mission_key"])
        if not dim:
            continue
        title = _mission_title(r["mission_key"])
        if r["status"] == "completed":
            _add(acc, dim, _MISSION_PASS_SCORE, _W_MISSION, f"미션 '{title}' 완료")
        else:
            _add(acc, dim, _MISSION_FAIL_SCORE, _W_MISSION, f"미션 '{title}' 실패")
        signals += 1
    return signals


# ------------------------------------------------------------
#  (d) 부정행위 근거
# ------------------------------------------------------------
def _collect_misconduct_evidence(conn: sqlite3.Connection, user_id: int,
                                 acc: dict) -> int:
    """판매자 부정행위(player_misconduct) 기록은 판매자 부정행위 회피 점수를 낮춘다."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM trade_results "
        "WHERE user_id = ? AND verdict = 'player_misconduct'",
        (user_id,),
    ).fetchone()
    n = int(row["c"]) if row and row["c"] is not None else 0
    if n <= 0:
        return 0
    _add(
        acc, "seller_misconduct_avoidance", _MISCONDUCT_SCORE, _W_MISCONDUCT,
        f"판매자 모드에서 부적절 대응(부정행위)으로 기록된 거래 {n}건",
    )
    return n


# ------------------------------------------------------------
#  다음 행동 추천
# ------------------------------------------------------------
def _recommended_next_actions(risk_dimensions: list[dict], has_assessment: bool) -> list[str]:
    """약한 차원 중심으로 구체적 다음 단계(진단/미션/훈련)를 제안한다."""
    actions: list[str] = []
    if not has_assessment:
        actions.append("먼저 기본 진단(baseline)을 완료해 약점 차원을 정확히 파악해 보세요.")
    for d in risk_dimensions[:3]:  # 가장 약한 3개 (weak→strong 정렬)
        if d.get("level") == "strong":
            continue
        meta = rs.dimension_meta(d["key"])
        train = meta.get("recommended_training") or ""
        if train:
            actions.append(f"[{d['label']}] {train}")
        titles = [_mission_title(k) for k in (meta.get("mission_keys") or [])]
        if titles:
            actions.append(f"[{d['label']}] 추천 미션: " + ", ".join(titles))
    if not actions:
        actions.append("현재 강점을 유지하며 새로운 유형의 시나리오로 훈련 범위를 넓혀 보세요.")
    return actions[:6]


# ------------------------------------------------------------
#  메인: 통합 위험 프로필
# ------------------------------------------------------------
def build_user_risk_profile(conn: sqlite3.Connection, user_id: int) -> dict:
    """네 갈래 근거를 블렌딩해 통합 위험 프로필(방어 훈련 데모 점수)을 만든다."""
    acc: dict[str, list[tuple[float, float, str]]] = {}
    signals = 0
    has_assessment = False

    # 각 소스는 실패해도 요청을 죽이지 않도록 개별 try/except.
    try:
        s, has_assessment = _collect_assessment_evidence(conn, user_id, acc)
        signals += s
    except Exception:
        pass
    try:
        signals += _collect_gameplay_evidence(conn, user_id, acc)
    except Exception:
        pass
    try:
        signals += _collect_mission_evidence(conn, user_id, acc)
    except Exception:
        pass
    try:
        signals += _collect_misconduct_evidence(conn, user_id, acc)
    except Exception:
        pass

    risk_dimensions: list[dict] = []
    scored_values: list[int] = []
    strengths: list[str] = []
    weaknesses: list[str] = []

    for key in rs.DIMENSION_KEYS:
        meta = rs.dimension_meta(key)
        contribs = acc.get(key)
        if not contribs:
            continue  # 근거 없는 차원은 목록에서 제외 (unknown)
        wsum = sum(w for _, w, _ in contribs)
        if wsum <= 0:
            continue
        score = int(round(sum(s * w for s, w, _ in contribs) / wsum))
        score = max(0, min(100, score))
        level = rs.level_for_score(score)
        risk_dimensions.append({
            "key": key,
            "label": meta["label"],
            "score": score,
            "level": level,
            "level_label": rs.level_label_ko(level),
            "evidence": [ev for _, _, ev in contribs],
            "recommended_training": meta.get("recommended_training", ""),
        })
        scored_values.append(score)
        if level == "strong":
            strengths.append(meta["label"])
        elif level == "weak":
            weaknesses.append(meta["label"])

    # 약함 → 강함 정렬 (점수 오름차순)
    risk_dimensions.sort(key=lambda d: d["score"])

    overall = int(round(sum(scored_values) / len(scored_values))) if scored_values else 0

    return {
        "overall_risk_score": overall,
        "confidence": rs.confidence_from_evidence(signals),
        "risk_dimensions": risk_dimensions,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_next_actions": _recommended_next_actions(risk_dimensions, has_assessment),
        "disclaimer": rs.DISCLAIMER,
        "is_demo": True,
    }
