"""
심판 / 코치 에이전트.

역할극 에이전트와는 '다른 직업'의 두 번째 AI 다.
- 역할극 에이전트: 끝까지 연기 / 정답 모르는 척 / 창의적(temperature 높음)
- 심판 에이전트:   정답지를 받음 / 객관적 채점 / 일관성 중요(temperature 낮음)

두 모드를 모두 채점한다:
  - 구매자 모드: evaluate()             → 사기꾼/정상 판별 (기존)
  - 판매자 모드: evaluate_seller_mode() → 진상/위험 구매자 대응 (신규)

설계 원칙(중요): 최종 '정오(correct)'와 verdict 는 규칙 기반으로 결정한다.
LLM 은 코칭 문구와 뉘앙스에만 쓴다 (LLM 이 정답을 직접 못 정하게).
제공자(openai/local_claude)가 실패하면 정적 mock 으로 폴백한다.
"""
from __future__ import annotations

from app.ai.personas import BUYER_BEHAVIORS, TACTICS
from app.ai.privacy import sanitize_message
from app.ai.prompts import (
    build_judge_system_prompt,
    build_judge_user_payload,
    build_seller_mode_judge_system_prompt,
    build_seller_mode_judge_user_payload,
)
from app.ai.provider import active_provider, call_llm_json
from app.config import get_settings

# ---- 구매자 모드: 결정 x 정체 → (verdict, 옳은가) ----
_VERDICT_TABLE = {
    ("scammer", "report"): ("good_catch", True),
    ("scammer", "walk_away"): ("good_catch", True),
    ("scammer", "buy"): ("scammed", False),
    ("honest", "buy"): ("safe", True),
    ("honest", "walk_away"): ("missed_deal", False),
    ("honest", "report"): ("missed_deal", False),
}

# ---- 판매자 모드: 구매자유형 x 결정 → (verdict, 옳은가) ----
_SELLER_VERDICT_TABLE = {
    ("honest_buyer", "complete_sale"): ("fair_sale", True),
    ("honest_buyer", "partial_refund"): ("fair_sale", True),
    ("honest_buyer", "refuse_refund"): ("fair_sale", True),
    ("honest_buyer", "accept_refund"): ("over_refunded", False),
    ("honest_buyer", "escalate_platform"): ("lost_sale", False),
    ("honest_buyer", "cancel_trade"): ("lost_sale", False),

    ("refund_villain", "refuse_refund"): ("handled_refund_villain", True),
    ("refund_villain", "escalate_platform"): ("handled_refund_villain", True),
    ("refund_villain", "complete_sale"): ("handled_refund_villain", True),
    ("refund_villain", "partial_refund"): ("over_refunded", False),
    ("refund_villain", "accept_refund"): ("over_refunded", False),
    ("refund_villain", "cancel_trade"): ("over_refunded", False),

    ("lowballer", "complete_sale"): ("fair_sale", True),
    ("lowballer", "refuse_refund"): ("handled_lowballer", True),
    ("lowballer", "cancel_trade"): ("handled_lowballer", True),
    ("lowballer", "escalate_platform"): ("handled_lowballer", True),
    ("lowballer", "partial_refund"): ("over_refunded", False),
    ("lowballer", "accept_refund"): ("over_refunded", False),

    ("ghosting_buyer", "complete_sale"): ("fair_sale", True),
    ("ghosting_buyer", "cancel_trade"): ("ok_walkaway", True),
    ("ghosting_buyer", "refuse_refund"): ("ok_walkaway", True),
    ("ghosting_buyer", "escalate_platform"): ("ok_walkaway", True),
    ("ghosting_buyer", "accept_refund"): ("over_refunded", False),
    ("ghosting_buyer", "partial_refund"): ("over_refunded", False),

    ("risky_buyer", "cancel_trade"): ("handled_risky", True),
    ("risky_buyer", "escalate_platform"): ("handled_risky", True),
    ("risky_buyer", "refuse_refund"): ("handled_risky", True),
    ("risky_buyer", "complete_sale"): ("unsafe_response", False),
    ("risky_buyer", "accept_refund"): ("unsafe_response", False),
    ("risky_buyer", "partial_refund"): ("unsafe_response", False),

    # 정당한 하자 주장: 판매자가 고지를 빠뜨린 진짜 하자 → 합리적으로 해결해야 옳다.
    ("legit_claim_buyer", "accept_refund"): ("fair_sale", True),
    ("legit_claim_buyer", "partial_refund"): ("fair_sale", True),
    ("legit_claim_buyer", "escalate_platform"): ("fair_sale", True),
    ("legit_claim_buyer", "cancel_trade"): ("fair_sale", True),
    ("legit_claim_buyer", "refuse_refund"): ("missed_legitimate_claim", False),
    ("legit_claim_buyer", "complete_sale"): ("missed_legitimate_claim", False),
}

# 판매자가 쓰면 안 되는 욕설/위협성 표현 (감지되면 unsafe_response 로 강등).
# 주의: 부분문자열로 매칭하므로, 정상 거래 문구에 섞일 수 있는 모호한 어간은 피한다.
#   - "죽여" → "죽여주는 가격"(=대박 가격) 오탐 → "죽여버"/"죽을래" 같은 협박형만 둔다.
#   - "찾아갈/찾아간다" → "제가 찾아갈게요"(=직거래하러 감) 오탐 → "집까지 찾아" 형태만 둔다.
_ABUSIVE = [
    # 욕설 (이 형태로는 정상 거래 문구에 거의 안 나온다)
    "씨발", "시발", "씨팔", "개새", "개색", "병신", "미친놈", "미친년",
    "꺼져", "지랄", "닥쳐", "엿먹", "좆같", "썅",
    # 위협성 표현 — 협박이 분명한 형태만
    "죽여버", "죽을래", "고소미", "가만 안", "가만안", "가만두지",
    "집까지 찾아", "집으로 찾아", "신상 털",
]


class JudgeAgent:
    # ============================================================
    #  구매자 모드 (기존)
    # ============================================================
    def evaluate(self, npc: dict, transcript: list[dict], decision: str) -> dict:
        # 1) 규칙 기반으로 정오/verdict/점수/플래그를 먼저 확정 (권위 있는 결과).
        #    (판매자 모드와 동일한 원칙 — LLM 이 점수/정답을 좌우하지 못하게 한다.)
        base = self._evaluate_mock(npc, transcript, decision)
        # 2) 제공자가 있으면 '코칭 문구'만 LLM 으로 다듬는다.
        if active_provider() != "mock":
            try:
                system_prompt = build_judge_system_prompt()
                user_payload = build_judge_user_payload(npc, transcript, decision)
                result = call_llm_json(
                    system_prompt,
                    [{"role": "user", "content": user_payload}],
                    use_judge_model=True,
                    temperature=0.2,
                    model=get_settings().claude_model_judge,
                )
                coaching = sanitize_message(str(result.get("coaching", "")))
                if coaching:
                    base["coaching"] = coaching
            except Exception:
                # 코칭만 다듬는 단계 — 실패해도 규칙기반 base 를 그대로 쓴다 (게임은 멈추지 않음)
                pass
        return base

    def _evaluate_mock(self, npc: dict, transcript: list[dict], decision: str) -> dict:
        verdict, correct = _VERDICT_TABLE.get((npc["role"], decision), ("scammed", False))
        tactic_msgs = [
            m for m in transcript
            if m["speaker"] == "npc" and m.get("tactic") not in (None, "none")
        ]
        flagged = [m for m in tactic_msgs if m.get("flagged_by_player")]
        detected = sorted({
            TACTICS[m["tactic"]]["red_flag"]
            for m in flagged if m["tactic"] in TACTICS
        })
        missed = sorted({
            TACTICS[m["tactic"]]["red_flag"]
            for m in tactic_msgs
            if m["tactic"] in TACTICS and not m.get("flagged_by_player")
        })
        # 목표: '정상 판매자에게서 구매 성공' 이 최고 점수. 사기 회피도 좋지만 그다음.
        if verdict == "safe":            # 정상 판매자에게 안전하게 구매 = 핵심 목표 달성
            score = 90 + (10 if not tactic_msgs else 0)   # 보통 100
        elif verdict == "good_catch":    # 사기꾼을 피함 (돈은 지켰지만 구매는 못 함)
            score = 72
            if tactic_msgs:
                score += round(23 * len(flagged) / len(tactic_msgs))
        elif verdict == "missed_deal":   # 정상 판매자인데 구매를 놓침
            score = 18
        else:                            # scammed — 사기당해 돈을 날림
            score = 0
        score = self._clamp_score(score)
        return {
            "verdict": verdict,
            "correct": correct,
            "score": score,
            "detected_flags": detected,
            "missed_flags": missed,
            "coaching": self._fallback_coaching(npc, decision, correct),
        }

    @staticmethod
    def _fallback_coaching(npc: dict, decision: str, correct: bool) -> str:
        if npc["role"] == "scammer":
            if correct:
                return (
                    "좋아요. 상대가 흐름을 잡기 전에 끊어냈어요. "
                    "다음엔 같은 수법이 포장만 바꿔 들어와도 똑같이 막아내면 됩니다."
                )
            return (
                "이번엔 상대 페이스에 말렸어요. 선입금 요구나 외부 링크가 보이면 "
                "설득하려 들지 말고 그 순간 바로 멈추는 게 가장 안전합니다."
            )
        if correct:
            return (
                "정상 판매자를 잘 알아봤어요. 검증은 다 하면서도 무고한 사람을 "
                "사기꾼 취급하지 않은 균형감이 좋았습니다."
            )
        return (
            "이 판매자는 사실 정상이었어요. 싸거나 불친절하다는 것만으로 사기로 "
            "단정하면 멀쩡한 거래를 놓칩니다. 링크·선입금 같은 '행동'을 기준으로 보세요."
        )

    # ============================================================
    #  판매자 모드 (신규)
    # ============================================================
    def evaluate_seller_mode(self, npc: dict, transcript: list[dict], decision: str) -> dict:
        # 1) 규칙 기반으로 정오/verdict/점수/플래그를 먼저 확정 (권위 있는 결과)
        base = self._evaluate_seller_mock(npc, transcript, decision)
        # 2) 제공자가 있으면 '코칭 문구'만 LLM 으로 다듬는다
        if active_provider() != "mock":
            try:
                system_prompt = build_seller_mode_judge_system_prompt()
                payload = build_seller_mode_judge_user_payload(npc, transcript, decision)
                result = call_llm_json(
                    system_prompt,
                    [{"role": "user", "content": payload}],
                    use_judge_model=True,
                    temperature=0.2,
                    model=get_settings().claude_model_judge,
                )
                coaching = sanitize_message(str(result.get("coaching", "")))
                if coaching:
                    base["coaching"] = coaching
            except Exception:
                # 코칭 문구만 LLM 으로 다듬는 단계 — 실패해도 규칙기반 base 를 그대로 쓴다
                pass
        return base

    def _evaluate_seller_mock(self, npc: dict, transcript: list[dict], decision: str) -> dict:
        btype = npc["role"]
        verdict, correct = _SELLER_VERDICT_TABLE.get((btype, decision), ("unsafe_response", False))

        beh_msgs = [
            m for m in transcript
            if m["speaker"] == "npc" and m.get("tactic") not in (None, "none")
        ]
        flagged = [m for m in beh_msgs if m.get("flagged_by_player")]
        detected = sorted({
            BUYER_BEHAVIORS[m["tactic"]]["red_flag"]
            for m in flagged
            if m["tactic"] in BUYER_BEHAVIORS and BUYER_BEHAVIORS[m["tactic"]]["red_flag"]
        })
        missed = sorted({
            BUYER_BEHAVIORS[m["tactic"]]["red_flag"]
            for m in beh_msgs
            if m["tactic"] in BUYER_BEHAVIORS and not m.get("flagged_by_player")
            and BUYER_BEHAVIORS[m["tactic"]]["red_flag"]
        })

        player_text = " ".join(m["content"] for m in transcript if m["speaker"] == "player")
        abusive = any(w in player_text for w in _ABUSIVE)

        # 목표: 내 물건을 '환불 없이' 끝까지 잘 파는 것.
        #  - 올바른 대응(판매 유지/빌런 방어/정당한 해결) = 높은 점수
        #  - 정상 거래를 놓치거나(lost_sale) 괜한 환불(over_refunded) = 큰 감점
        score = 72 if correct else 18
        # 가점(증거 활용·플랫폼 절차·위험행동 포착)은 '올바른 결정'일 때만 준다.
        # 틀린 결정(정상 거래 놓침/괜한 환불)에 부분점수를 주지 않기 위함 (구매자 채점과 동일 원칙).
        if correct:
            if any(k in player_text for k in ("상태", "사진", "영상", "기록", "고지", "구성품", "설명")):
                score += 10  # 증거/고지 활용
            if any(k in player_text for k in ("안전결제", "플랫폼", "분쟁", "고객센터", "정식")):
                score += 10  # 플랫폼 안전 절차
            if beh_msgs:
                score += round(8 * len(flagged) / len(beh_msgs))  # 위험 행동 포착

        if abusive:
            # 욕설/위협은 그 자체로 불안전 대응 — 무작정 화내고 거래 망치면 크게 깎인다.
            verdict, correct = "unsafe_response", False
            score = min(score, 6)
            missed = sorted(set(missed) | {"판매자가 감정적·공격적으로 대응함 (욕설/위협 금지)"})

        score = self._clamp_score(score)
        return {
            "verdict": verdict,
            "correct": correct,
            "score": score,
            "detected_flags": detected,
            "missed_flags": missed,
            "coaching": self._seller_fallback_coaching(btype, decision, correct, abusive),
        }

    @staticmethod
    def _seller_fallback_coaching(btype: str, decision: str, correct: bool, abusive: bool) -> str:
        if abusive:
            return (
                "대응이 감정적으로 흘렀어요. 상대가 무례해도 욕설·위협은 오히려 나를 불리하게 만듭니다. "
                "감정은 빼고 사실·기록·플랫폼 절차로만 말하는 연습을 해보세요."
            )
        msgs = {
            "honest_buyer": (
                "정상적인 구매자였어요. 깔끔하게 거래를 마무리한 게 좋았습니다.",
                "정상 구매자에게 과하게 방어적이면 멀쩡한 거래를 놓쳐요. 의심은 '행동'을 보고 하세요.",
            ),
            "refund_villain": (
                "환불 빌런을 잘 막았어요. 고지·기록을 근거로 흔들리지 않은 게 핵심이었습니다.",
                "근거 없는 환불 요구에 휘둘렸어요. 거래 당시 상태 고지와 대화 기록을 근거로 정중히 거절하거나 플랫폼 분쟁으로 넘기세요.",
            ),
            "lowballer": (
                "가격선을 잘 지켰어요. 막깎이엔 분명한 기준선이 답입니다.",
                "감정 호소·과한 후려치기에 말렸어요. 원하는 가격을 미리 정하고 안 맞으면 정중히 정리하세요.",
            ),
            "ghosting_buyer": (
                "간만 보는 구매자에게 시간을 적게 쓴 게 좋아요. 담담히 다음 거래로 넘어가면 됩니다.",
                "잠수러에게 무리한 약속·선점 보장을 하면 손해예요. 약속은 기록으로 남기고 담담히 진행하세요.",
            ),
            "risky_buyer": (
                "위험한 거래 유도를 잘 거절했어요. 결제·직거래는 안전한 방식만 고집하는 게 정답입니다.",
                "외부 결제·이상한 직거래 유도를 받아주면 위험해요. 안전결제·공공장소 직거래만 고수하고, 안 되면 거래를 접으세요.",
            ),
            "legit_claim_buyer": (
                "고지 못 한 진짜 하자였어요. 발뺌하지 않고 합리적으로 해결한 게 좋은 태도입니다.",
                "이번엔 판매자 쪽 고지 누락이 있는 '정당한' 요구였어요. 무조건 거절하기보다 부분환불·환불·플랫폼 절차로 합리적으로 풀어야 신뢰가 쌓입니다.",
            ),
        }
        good, bad = msgs.get(btype, ("거래를 마무리했어요.", "다음엔 기록과 플랫폼 절차를 더 적극적으로 활용해 보세요."))
        return good if correct else bad

    # ---- 공통 ----
    @staticmethod
    def _clamp_score(score) -> int:
        try:
            return max(0, min(100, int(score)))
        except (ValueError, TypeError):
            return 0


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]
