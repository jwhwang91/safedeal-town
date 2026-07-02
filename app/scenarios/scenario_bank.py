"""
방어 시나리오 뱅크 (저장 / 데모 시드 / 조회).

⚠️ 여기 담기는 시나리오는 전부 '픽션화된 방어 훈련 자료'다.
   실제 사기 수법·실명·계좌/전화/URL 을 담지 않는다. 커뮤니티 사례에서
   변환된 시나리오도 원문을 그대로 복제하지 않고 '일반화된 위험 패턴'으로 추상화한다.

점수/승인 관례:
  - status: 'draft' | 'pending_review' | 'approved' | 'rejected'
  - 사례→시나리오 변환은 검토 게이트(case_scenario_requires_review)에 따라
    기본 status 가 'pending_review'(검토 필요) 또는 'approved'(즉시 공개)가 된다.
  - 데모 시드는 항상 'approved' + source_type='builtin_demo'.

이 계층(DB 계층)은 commit 하지 않는다 — 호출자(라우터/마이그레이션)가 commit 한다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import get_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# 클라이언트로 나가면 안 되는 내부 라벨 키 (persona_seed 는 labels 테이블에 특수 저장)
_PERSONA_SEED_LABEL = "persona_seed"


def _as_list(val) -> list:
    """JSON 문자열/리스트/None 을 안전하게 리스트로 정규화."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _as_obj(val) -> dict:
    """JSON 문자열/딕트/None 을 안전하게 딕트로 정규화."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _field(obj, key, default=None):
    """dict 이든 sqlite3.Row 이든 안전하게 필드를 꺼낸다 (없으면 default)."""
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        if hasattr(obj, "keys") and key in obj.keys():
            return obj[key]
    except Exception:
        pass
    return default


# ============================================================
#  저장
# ============================================================
def store_scenario(
    conn: sqlite3.Connection,
    scenario: dict,
    *,
    source_type: str,
    source_case_id: str | None = None,
    created_by: str = "system",
    status: str | None = None,
) -> str:
    """시나리오 한 건을 scenario_bank 에 저장하고 scenario_id 를 돌려준다.

    scenario 딕트 형태:
      {title, category, risk_family, scenario_summary, red_flags:[...],
       safe_counters:[...], difficulty, labels:{k:v}(선택), persona_seed:{...}(선택)}

    status 가 None 이면 검토 게이트를 따른다:
      case_scenario_requires_review -> 'pending_review' 아니면 'approved'.
    """
    scenario = scenario or {}
    category = str(scenario.get("category") or "").strip()
    risk_family = str(scenario.get("risk_family") or "").strip()
    if not category:
        raise ValueError("scenario.category 는 비어 있을 수 없어요.")
    if not risk_family:
        raise ValueError("scenario.risk_family 는 비어 있을 수 없어요.")

    if status is None:
        status = (
            "pending_review"
            if get_settings().case_scenario_requires_review
            else "approved"
        )

    scenario_id = _new_id()
    now = _now()
    title = str(scenario.get("title") or "제목 없는 방어 시나리오").strip()
    summary = str(scenario.get("scenario_summary") or "").strip()
    red_flags = _as_list(scenario.get("red_flags"))
    safe_counters = _as_list(scenario.get("safe_counters"))
    difficulty = str(scenario.get("difficulty") or "medium").strip() or "medium"

    conn.execute(
        """
        INSERT INTO scenario_bank
          (id, source_type, source_case_id, category, risk_family, title,
           scenario_summary, red_flags_json, safe_counters_json, difficulty,
           status, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scenario_id, source_type, source_case_id, category, risk_family, title,
            summary,
            json.dumps(red_flags, ensure_ascii=False),
            json.dumps(safe_counters, ensure_ascii=False),
            difficulty, status, created_by, now, now,
        ),
    )

    # 라벨(선택) + persona_seed(선택)를 scenario_labels 에 저장 (스키마 추가 없이).
    try:
        labels = scenario.get("labels") or {}
        if isinstance(labels, dict):
            for label_key, label_value in labels.items():
                if label_key is None:
                    continue
                conn.execute(
                    """
                    INSERT INTO scenario_labels
                      (id, scenario_id, label_key, label_value, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(), scenario_id, str(label_key),
                        json.dumps(label_value, ensure_ascii=False)
                        if not isinstance(label_value, str) else label_value,
                        0.8, now,
                    ),
                )
        persona_seed = scenario.get("persona_seed")
        if isinstance(persona_seed, dict) and persona_seed:
            conn.execute(
                """
                INSERT INTO scenario_labels
                  (id, scenario_id, label_key, label_value, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id(), scenario_id, _PERSONA_SEED_LABEL,
                    json.dumps(persona_seed, ensure_ascii=False), 1.0, now,
                ),
            )
    except Exception:
        # 라벨 저장 실패는 시나리오 본체 저장을 무효화하지 않는다.
        pass

    return scenario_id


# ============================================================
#  조회
# ============================================================
def get_scenario(conn: sqlite3.Connection, scenario_id: str) -> dict | None:
    """시나리오 한 건을 (파싱된 JSON + 라벨/persona_seed 포함) 딕트로 돌려준다."""
    row = conn.execute(
        "SELECT * FROM scenario_bank WHERE id = ?", (scenario_id,)
    ).fetchone()
    if not row:
        return None

    labels: dict = {}
    persona_seed: dict | None = None
    try:
        for lr in conn.execute(
            "SELECT label_key, label_value FROM scenario_labels WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchall():
            key = lr["label_key"]
            val = lr["label_value"]
            if key == _PERSONA_SEED_LABEL:
                persona_seed = _as_obj(val)
            else:
                # 라벨 값은 JSON 이었다면 파싱, 아니면 원문 문자열
                try:
                    labels[key] = json.loads(val)
                except Exception:
                    labels[key] = val
    except Exception:
        pass

    return {
        "id": row["id"],
        "source_type": row["source_type"],
        "source_case_id": row["source_case_id"],
        "category": row["category"],
        "risk_family": row["risk_family"],
        "title": row["title"],
        "scenario_summary": row["scenario_summary"],
        "red_flags": _as_list(row["red_flags_json"]),
        "safe_counters": _as_list(row["safe_counters_json"]),
        "difficulty": row["difficulty"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "labels": labels,
        "persona_seed": persona_seed,
    }


def public_scenario(row_or_dict) -> dict:
    """클라이언트로 내보내도 안전한 시나리오 형태.

    scenario_bank Row / get_scenario 딕트 / 생성기 시나리오 딕트 모두 받는다.
    원본 개인정보나 source_case_id 같은 내부 필드는 절대 포함하지 않는다.
    """
    obj = row_or_dict or {}

    red_flags = _field(obj, "red_flags")
    if red_flags is None:
        red_flags = _field(obj, "red_flags_json", "[]")
    safe_counters = _field(obj, "safe_counters")
    if safe_counters is None:
        safe_counters = _field(obj, "safe_counters_json", "[]")

    result = {
        "id": _field(obj, "id"),
        "title": _field(obj, "title", ""),
        "category": _field(obj, "category", ""),
        "risk_family": _field(obj, "risk_family", ""),
        "scenario_summary": _field(obj, "scenario_summary", ""),
        "red_flags": _as_list(red_flags),
        "safe_counters": _as_list(safe_counters),
        "difficulty": _field(obj, "difficulty", "medium"),
        "status": _field(obj, "status", "approved"),
        "source_type": _field(obj, "source_type", ""),
    }

    persona_seed = _field(obj, "persona_seed")
    if isinstance(persona_seed, str):
        persona_seed = _as_obj(persona_seed)
    if isinstance(persona_seed, dict) and persona_seed:
        result["persona_seed"] = persona_seed

    return result


def list_scenarios(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    category: str | None = None,
    risk_family: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """조건에 맞는 시나리오 목록(공개 형태)."""
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
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(int(limit) if limit else 50)

    rows = conn.execute(sql, params).fetchall()
    return [public_scenario(r) for r in rows]


def approve_scenario(conn: sqlite3.Connection, scenario_id: str) -> bool:
    """시나리오를 approved 로 승인 (데모/관리자 편의). 존재하면 True."""
    row = conn.execute(
        "SELECT id FROM scenario_bank WHERE id = ?", (scenario_id,)
    ).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE scenario_bank SET status = 'approved', updated_at = ? WHERE id = ?",
        (_now(), scenario_id),
    )
    return True


# ============================================================
#  데모 시드 (마이그레이션이 부팅 때 호출 — 시그니처 고정)
# ============================================================
# 6~8개의 픽션·방어 시나리오. 카테고리/위험군을 폭넓게 커버.
# 실제 계좌/전화/URL 은 절대 넣지 않는다.
_DEMO_SCENARIOS: list[dict] = [
    {
        "id": "demo_scn_off_platform_link",
        "category": "used_marketplace",
        "risk_family": "off_platform_link",
        "title": "앱 밖 링크로 결제를 유도하는 판매자",
        "scenario_summary": (
            "판매자가 '앱 수수료가 아깝다', '더 빠르다'며 외부 사이트 링크에서 "
            "결제하자고 유도한다. 링크 밖으로 나가면 플랫폼 보호를 못 받게 된다."
        ),
        "red_flags": [
            "앱 밖 외부 링크에서 결제하자고 유도한다",
            "'수수료 아깝다/더 빠르다'로 정식 절차를 건너뛰라 한다",
            "대화를 앱 밖으로 옮기려 한다",
        ],
        "safe_counters": [
            "외부 링크는 누르지 않고 앱 내 공식 결제만 쓴다",
            "'앱 안에서만 진행하겠다'고 정중히 단호하게 말한다",
            "이상하면 거래를 멈추고 신고 버튼을 확인한다",
        ],
        "difficulty": "easy",
    },
    {
        "id": "demo_scn_delivery_payment",
        "category": "delivery_trade_safety",
        "risk_family": "delivery_payment_risk",
        "title": "실물 확인 전 선입금을 재촉하는 택배거래",
        "scenario_summary": (
            "택배거래인데 '지금 입금해야 물건을 빼둔다'며 실물 확인 전 선입금을 재촉한다. "
            "확인 절차 없이 먼저 돈을 보내면 회수가 어렵다."
        ),
        "red_flags": [
            "실물/구성품 확인 전에 선입금을 요구한다",
            "'지금 안 넣으면 다른 사람에게 넘긴다'로 재촉한다",
            "안전결제 대신 계좌 이체를 고집한다",
        ],
        "safe_counters": [
            "확인 전 입금은 금액이 작아도 거절한다",
            "실물 사진·구성품·상태를 먼저 요청한다",
            "플랫폼 안전결제 절차만 사용한다",
        ],
        "difficulty": "medium",
    },
    {
        "id": "demo_scn_personal_contact",
        "category": "private_contact_boundary",
        "risk_family": "personal_contact_grooming",
        "title": "앱 밖 개인 연락으로 옮기자는 상대",
        "scenario_summary": (
            "상대가 '여기 불편하다'며 개인 메신저/전화로 연락을 옮기자고 한다. "
            "대화가 앱 밖으로 나가면 기록이 사라지고 보호도 약해진다."
        ),
        "red_flags": [
            "개인 메신저·전화로 연락을 옮기자고 한다",
            "친구 추가/오픈채팅 등 사적 채널을 권한다",
            "'여기서 말고'라며 플랫폼 대화를 피한다",
        ],
        "safe_counters": [
            "'거래 대화는 앱 안에서만 하겠다'고 선을 긋는다",
            "정중하지만 단호하게 개인 연락 유도를 거절한다",
            "기록이 남는 플랫폼 대화를 유지한다",
        ],
        "difficulty": "easy",
    },
    {
        "id": "demo_scn_romance_boundary",
        "category": "romance_scam",
        "risk_family": "romance_boundary_pressure",
        "title": "호감을 앞세워 판단을 흐리는 접근",
        "scenario_summary": (
            "짧은 대화에도 지나친 호감·친밀감을 표현하며 신뢰를 앞세운다. "
            "감정적 신뢰가 거래/금전 판단을 흐리게 만드는 전형적 압박이다."
        ),
        "red_flags": [
            "만난 지 얼마 안 됐는데 과한 애정/신뢰를 표현한다",
            "감정을 근거로 금전·거래 부탁을 슬쩍 끼운다",
            "'우리 사이에 왜 못 믿냐'로 경계를 무너뜨린다",
        ],
        "safe_counters": [
            "감정과 거래 판단을 분리한다",
            "금전이 얽히면 한 박자 멈추고 사실만 확인한다",
            "친밀감을 이유로 절차를 건너뛰지 않는다",
        ],
        "difficulty": "medium",
    },
    {
        "id": "demo_scn_refund_conflict",
        "category": "seller_refund_conflict",
        "risk_family": "refund_conflict",
        "title": "근거 없이 환불을 압박하는 구매자",
        "scenario_summary": (
            "판매자 입장에서, 구매자가 명확한 하자 근거 없이 협박성 어조로 환불을 요구한다. "
            "감정에 휘말리지 않고 고지·기록 중심으로 대응해야 하는 상황."
        ),
        "red_flags": [
            "구체적 하자 근거 없이 환불부터 요구한다",
            "악평·신고를 무기로 압박한다",
            "고지된 상태를 무시하고 책임을 전가한다",
        ],
        "safe_counters": [
            "감정 대신 사전 고지·거래 기록을 근거로 답한다",
            "정당한 하자 주장인지 사실 기준으로 구분한다",
            "침착하게 기준선을 유지하며 대화를 기록으로 남긴다",
        ],
        "difficulty": "hard",
    },
    {
        "id": "demo_scn_fake_safe_payment",
        "category": "used_marketplace",
        "risk_family": "fake_safe_payment",
        "title": "가짜 안전결제 페이지 유도",
        "scenario_summary": (
            "'안전결제로 하자'며 실제 플랫폼이 아닌 유사한 외부 안전결제 페이지 링크를 보낸다. "
            "정식 절차처럼 보이지만 플랫폼 밖이라 보호를 받지 못한다."
        ),
        "red_flags": [
            "플랫폼이 아닌 외부 '안전결제' 링크를 보낸다",
            "정식 화면과 비슷하게 꾸며 신뢰를 유도한다",
            "링크에서 추가 정보/결제를 입력하라 한다",
        ],
        "safe_counters": [
            "안전결제는 앱 내 공식 기능으로만 확인한다",
            "외부 링크의 결제/정보 입력 요구는 거절한다",
            "URL/화면이 조금이라도 다르면 진행을 멈춘다",
        ],
        "difficulty": "medium",
    },
    {
        "id": "demo_scn_voice_call_pressure",
        "category": "voice_phishing",
        "risk_family": "voice_call_pressure",
        "title": "전화 본인확인·인증을 압박하는 상대",
        "scenario_summary": (
            "'본인확인이 필요하다'며 전화 통화나 외부 인증을 재촉한다. "
            "통화로 넘어가 인증번호/정보를 부르게 만드는 압박 패턴이다."
        ),
        "red_flags": [
            "전화 통화·외부 인증을 급하게 요구한다",
            "인증번호/개인정보를 불러달라 한다",
            "'지금 안 하면 큰일 난다'로 겁을 준다",
        ],
        "safe_counters": [
            "전화·외부 인증 요구는 공식 채널로만 확인한다",
            "인증번호·개인정보는 누구에게도 불러주지 않는다",
            "재촉당할수록 한 박자 멈추고 확인한다",
        ],
        "difficulty": "hard",
    },
    {
        "id": "demo_scn_investment_pressure",
        "category": "investment_scam",
        "risk_family": "investment_pressure",
        "title": "고수익을 앞세운 투자 재촉",
        "scenario_summary": (
            "'확정 수익', '지금만 기회'라며 빠른 결정을 재촉한다. "
            "지나치게 좋은 조건과 시간 압박이 겹치는 전형적 유인이다."
        ),
        "red_flags": [
            "'원금 보장/확정 수익'을 장담한다",
            "'오늘만/지금만'으로 결정을 재촉한다",
            "검증 없이 외부 채널/링크로 유도한다",
        ],
        "safe_counters": [
            "'너무 좋은 조건'일수록 왜 그런지 먼저 의심한다",
            "재촉에는 결정을 미루고 독립적으로 확인한다",
            "확정 수익 약속은 신뢰의 근거가 아니라 위험 신호로 본다",
        ],
        "difficulty": "medium",
    },
]


def seed_demo_scenarios(conn: sqlite3.Connection) -> None:
    """내장 데모 시나리오를 멱등하게 시드한다 (마이그레이션이 부팅 때 호출).

    이미 builtin_demo 시나리오가 있으면 건너뛴다. 각 행은 고정 id + INSERT OR IGNORE
    라 여러 번 호출돼도 안전하다. commit 은 호출자가 한다.
    """
    try:
        existing = conn.execute(
            "SELECT COUNT(*) AS c FROM scenario_bank WHERE source_type = 'builtin_demo'"
        ).fetchone()
        if existing and existing["c"] and int(existing["c"]) > 0:
            return
    except Exception:
        # 카운트 실패해도 아래 INSERT OR IGNORE 로 안전하게 진행
        pass

    now = _now()
    for scn in _DEMO_SCENARIOS:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO scenario_bank
                  (id, source_type, source_case_id, category, risk_family, title,
                   scenario_summary, red_flags_json, safe_counters_json, difficulty,
                   status, created_by, created_at, updated_at)
                VALUES (?, 'builtin_demo', NULL, ?, ?, ?, ?, ?, ?, ?, 'approved',
                        'system', ?, ?)
                """,
                (
                    scn["id"], scn["category"], scn["risk_family"], scn["title"],
                    scn["scenario_summary"],
                    json.dumps(scn["red_flags"], ensure_ascii=False),
                    json.dumps(scn["safe_counters"], ensure_ascii=False),
                    scn.get("difficulty", "medium"), now, now,
                ),
            )
        except Exception:
            # 개별 시드 실패가 전체 부팅을 막지 않게 한다.
            continue
