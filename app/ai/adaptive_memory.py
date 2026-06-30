"""
적응형 훈련 메모리 기록기.

거래 한 판이 끝나면(=resolve) 이 모듈이:
  1) 게임 역할/상대 종류를 정한다.
  2) '이 대화에서 실제로 등장한 위험 신호'를 규칙기반으로 추출한다.
  3) ai_session_outcomes 에 안전한 구조화 요약을 남긴다.
  4) ai_user_training_memory 의 패턴별 숙련도를 갱신한다.
  5) 프론트로 보여줘도 안전한 학습 요약(라벨/대응)만 돌려준다.

설계 원칙(중요):
  - 공식 정오/verdict 는 LLM 이 정하지 않는다. 규칙기반 JudgeAgent 결과(result)를 그대로 신뢰한다.
  - 여기선 그 결과를 '훈련 신호'로 환원할 뿐, 점수/정답을 바꾸지 않는다.
  - 원문 대화는 기본 저장 안 함. STORE_REDACTED_TRANSCRIPTS=true 일 때만 비식별 후 저장.
  - 어떤 예외가 나도 호출부(resolve)가 try/except 로 감싸므로 게임은 멈추지 않는다.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.ai import adaptive_repository as repo
from app.ai import pattern_taxonomy as taxonomy
from app.ai import transcript_redactor as redactor
from app.config import get_settings


# ============================================================
#  숙련도/우선순위 계산 (투명·튜닝 쉬움)
# ============================================================
def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_mastery(times_seen: int, times_detected: int,
                    times_resisted: int, times_failed: int,
                    is_risk: bool = True) -> float:
    """0.0(자주 놓침/실패) ~ ~0.85(꾸준히 잘 막음).

    완벽 처리 시 상한이 0.85 인 건 의도된 것(약간의 여유를 둬 '항상 우선' 상태를 피함).
    is_risk=False 인 비위험 패턴(정당한 하자 주장 등)은 '포착(detection)' 개념이 없으므로
    저항(resistance)/실패(failure)로만 채점해, 구조적으로 0.5 에 갇히지 않게 한다.
    """
    if times_seen <= 0:
        return 0.15
    resistance_rate = times_resisted / times_seen
    failure_rate = times_failed / times_seen
    if not is_risk:
        return round(_clamp(0.15 + 0.70 * resistance_rate - 0.25 * failure_rate), 4)
    detection_rate = times_detected / times_seen
    return round(_clamp(
        0.15 + 0.35 * detection_rate + 0.35 * resistance_rate - 0.25 * failure_rate
    ), 4)


def compute_priority(mastery: float, recently_missed: bool,
                     repeated_too_much: bool) -> float:
    """높을수록 미래 훈련에 더 자주 등장해야 함."""
    score = 1.0 - mastery
    if recently_missed:
        score += 0.15
    if repeated_too_much:
        score -= 0.15
    return round(_clamp(score), 4)


def _within_recent_window(last_seen_at: str | None) -> bool:
    if not last_seen_at:
        return False
    try:
        dt = datetime.fromisoformat(last_seen_at)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = get_settings().adaptive_recent_avoid_window_days
    return (datetime.now(timezone.utc) - dt) <= timedelta(days=max(1, days))


# ============================================================
#  대화 → 등장한 패턴 추출 (규칙기반)
# ============================================================
def _extract_patterns(transcript: list[dict], game_role: str) -> dict:
    """대화에서 실제 등장한 위험 신호를 분류표 키로 환원한다.

    반환:
      seen      : 이 대화에서 등장한 모든 pattern_key (위험/비위험 포함)
      detected  : 위험 신호인데 사용자가 🚩 로 포착한 키
      missed    : 위험 신호인데 놓친 키
      flag_count: 사용자가 누른 의심표시 수 (정상 메시지 포함 — '과한 의심'도 집계)
    """
    # 의심표시 총수는 위험 패턴 여부와 무관하게 NPC 메시지 전체에서 센다
    # (정상 메시지에 🚩 를 누른 '과한 의심'도 보이도록).
    flag_count = sum(
        1 for m in (transcript or [])
        if m.get("speaker") == "npc" and m.get("flagged_by_player")
    )
    seen_flagged: dict[str, bool] = {}  # pattern_key → 한 번이라도 flag 됐나
    for m in transcript or []:
        if m.get("speaker") != "npc":
            continue
        tactic = m.get("tactic")
        if not tactic or tactic == "none":
            continue
        pk = taxonomy.pattern_key_for_label(tactic, game_role)
        if not pk:
            continue
        seen_flagged[pk] = seen_flagged.get(pk, False) or bool(m.get("flagged_by_player"))

    seen = sorted(seen_flagged.keys())
    detected, missed = [], []
    for pk in seen:
        if not taxonomy.is_risk_pattern(pk):
            continue  # 비위험(정당한 하자 주장 등)은 포착/놓침 대상이 아님
        if seen_flagged[pk]:
            detected.append(pk)
        else:
            missed.append(pk)
    return {
        "seen": seen,
        "detected": detected,
        "missed": missed,
        "flag_count": flag_count,
    }


# ============================================================
#  메모리 갱신 (패턴별)
# ============================================================
def _update_memory_for_pattern(conn, user_id: int, game_role: str, pattern_key: str,
                               *, detected: bool, missed: bool, correct: bool,
                               now: str) -> dict:
    pat = taxonomy.get_pattern(pattern_key)
    family = pat["pattern_family"] if pat else "unknown"
    prev = repo.get_memory_row(conn, user_id, game_role, pattern_key)

    times_seen = (prev["times_seen"] if prev else 0) + 1
    times_detected = (prev["times_detected"] if prev else 0) + (1 if detected else 0)
    times_missed = (prev["times_missed"] if prev else 0) + (1 if missed else 0)
    times_resisted = (prev["times_resisted"] if prev else 0) + (1 if correct else 0)
    times_failed = (prev["times_failed"] if prev else 0) + (0 if correct else 1)

    # recent_seen_count: 최근 창 안에서 또 봤으면 누적, 아니면 1로 리셋 (과반복 감지용)
    prev_last_seen = prev["last_seen_at"] if prev else None
    if prev and _within_recent_window(prev_last_seen):
        recent_seen_count = (prev["recent_seen_count"] or 0) + 1
    else:
        recent_seen_count = 1

    mastery = compute_mastery(times_seen, times_detected, times_resisted, times_failed,
                              is_risk=taxonomy.is_risk_pattern(pattern_key))
    repeated_too_much = recent_seen_count >= 2
    priority = compute_priority(mastery, recently_missed=missed,
                                repeated_too_much=repeated_too_much)

    # 충분히 숙달(>0.8)했고 방금 또 봤으면 잠시 덜 등장시킨다 (지루한 반복 방지)
    avoid_until = None
    if mastery > 0.8:
        days = get_settings().adaptive_recent_avoid_window_days
        avoid_until = (datetime.now(timezone.utc) + timedelta(days=max(1, days))).isoformat()

    fields = {
        "id": prev["id"] if prev else repo.new_id(),
        "user_id": user_id,
        "game_role": game_role,
        "pattern_key": pattern_key,
        "pattern_family": family,
        "times_seen": times_seen,
        "times_detected": times_detected,
        "times_missed": times_missed,
        "times_resisted": times_resisted,
        "times_failed": times_failed,
        "recent_seen_count": recent_seen_count,
        "last_seen_at": now,
        "mastery_score": mastery,
        "priority_score": priority,
        "avoid_repetition_until": avoid_until,
        "updated_at": now,
    }
    repo.write_training_memory(conn, fields)
    return fields


# ============================================================
#  공개 API
# ============================================================
def record_session_outcome(conn: sqlite3.Connection, user_id: int, session_id: str, *,
                           npc: dict, transcript: list[dict], result: dict,
                           checklist: dict | list | None = None,
                           rewards: dict | None = None,
                           game_role: str | None = None) -> dict:
    """완료된 거래 한 판을 적응형 메모리에 기록하고, 안전한 학습 요약을 돌려준다.

    /api/chat/resolve 에서 채점·보상 처리 후 호출된다. 호출부는 try/except 로 감싼다.
    game_role: 세션의 권위 있는 역할(trade_sessions.game_role). 채점/경제와 동일한 값으로
    버킷팅하기 위해 받는다. 없으면 npc.npc_kind 로 안전하게 유도한다.
    """
    settings = get_settings()
    game_role = game_role or ("seller" if npc.get("npc_kind") == "buyer" else "buyer")
    counterparty_kind = taxonomy.counterparty_kind_for(npc)

    ext = _extract_patterns(transcript, game_role)
    correct = bool(result.get("correct"))
    verdict = result.get("verdict")
    decision = result.get("decision")
    score = int(result.get("score") or 0)

    detected_set = set(ext["detected"])
    missed_set = set(ext["missed"])

    # 패턴별 메모리 갱신
    for pk in ext["seen"]:
        _update_memory_for_pattern(
            conn, user_id, game_role, pk,
            detected=pk in detected_set, missed=pk in missed_set,
            correct=correct, now=repo.utcnow_iso(),
        )

    # resisted/failed: 최종 결정 기준 (등장한 패턴 전체에 적용)
    resisted = ext["seen"] if correct else []
    failed = [] if correct else ext["seen"]

    turn_count = sum(1 for m in (transcript or []) if m.get("speaker") == "player")

    # 보상 요약(안전한 집계만)
    rw = rewards or {}
    reward_summary = {
        "coin_delta": rw.get("coin_delta"),
        "xp_delta": rw.get("xp_delta"),
        "item_gained": rw.get("item_gained"),
        "item_lost": rw.get("item_lost"),
        "leveled_up": bool(rw.get("leveled_up")),
    }

    # 체크리스트(자기보고) — dict 든 list 든 안전하게 보관
    if isinstance(checklist, list):
        checklist_payload = {"checked": [str(x) for x in checklist]}
    elif isinstance(checklist, dict):
        checklist_payload = checklist
    else:
        checklist_payload = {}

    redacted_json = None
    safety_tags = ["defensive_training_only"]
    if settings.store_redacted_transcripts:
        redacted_json = repo.json_dumps(redactor.redact_transcript(transcript))
        safety_tags.append("redacted_transcript_stored")

    coaching = result.get("coaching") or ""
    coaching_summary = redactor.redact_text(coaching)[:400] if coaching else None

    outcome = {
        "user_id": user_id,
        "session_id": session_id,
        "game_role": game_role,
        "counterparty_kind": counterparty_kind,
        "persona_id": npc.get("anchor_id") or npc.get("id"),
        "persona_family": npc.get("role_type") or npc.get("role"),
        "scenario_type": counterparty_kind,
        "category": npc.get("category"),
        "item_name": npc.get("item_name"),
        "difficulty": npc.get("difficulty"),
        "final_decision": decision,
        "verdict": verdict,
        "correct": 1 if correct else 0,
        "score": score,
        "detected_patterns_json": repo.json_dumps(ext["detected"]),
        "missed_patterns_json": repo.json_dumps(ext["missed"]),
        "resisted_patterns_json": repo.json_dumps(resisted),
        "failed_patterns_json": repo.json_dumps(failed),
        "checklist_json": repo.json_dumps(checklist_payload),
        "reward_summary_json": repo.json_dumps(reward_summary),
        "turn_count": turn_count,
        "flag_count": ext["flag_count"],
        "coaching_summary": coaching_summary,
        "transcript_digest": redactor.make_transcript_digest(transcript),
        "redacted_transcript_json": redacted_json,
        "safety_tags_json": repo.json_dumps(safety_tags),
    }
    repo.insert_session_outcome(conn, outcome)
    conn.commit()

    return build_learning_summary(ext["seen"], detected_set, missed_set, game_role)


def build_learning_summary(seen_keys: list[str], detected_set: set[str],
                           missed_set: set[str], game_role: str) -> dict:
    """결과 화면용 안전 요약. 내부 pattern_key 는 노출하지 않고 라벨/대응만 준다.

    - trained_signals : 이번 훈련에서 다룬 위험 신호(라벨 + red_flag + 안전 대응)
    - next_principle  : 다음에 조심할 핵심 원칙(놓친 신호 중 가장 위험한 것의 대응)
    """
    trained = []
    for pk in seen_keys:
        card = taxonomy.public_pattern_card(pk)
        if not card or not card.get("red_flag"):
            continue  # 위험 신호만 '훈련 카드'로 노출
        trained.append({
            "label": card["label"],
            "red_flag": card["red_flag"],
            "safe_counter": card["safe_counter"],
            "caught": pk in detected_set,
        })

    # 다음 원칙: 놓친 위험 신호 중 severity 가 가장 높은 것의 안전 대응
    next_principle = None
    missed_cards = [
        (taxonomy.get_pattern(pk), taxonomy.public_pattern_card(pk))
        for pk in sorted(missed_set)
    ]
    missed_cards = [(p, c) for p, c in missed_cards if p and c]
    if missed_cards:
        missed_cards.sort(key=lambda pc: pc[0].get("severity", 1), reverse=True)
        top = missed_cards[0][1]
        next_principle = top["safe_counter"]
    elif trained:
        # 다 잡았으면 가장 위험한 패턴의 원칙을 '복습 포인트'로
        sev_sorted = sorted(
            seen_keys, key=lambda k: (taxonomy.get_pattern(k) or {}).get("severity", 1),
            reverse=True,
        )
        for pk in sev_sorted:
            card = taxonomy.public_pattern_card(pk)
            if card and card.get("safe_counter"):
                next_principle = card["safe_counter"]
                break

    return {
        "trained_signals": trained,
        "next_principle": next_principle,
        "caught_count": len(detected_set),
        "missed_count": len(missed_set),
    }
