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

# ---- 방어 훈련 위험 구매자(사적 연락/로맨스/외부 인증/사회공학/괴롭힘) ----
# 정답 대응은 위험거래(risky_buyer)와 같은 골격: 앱 안 유지·선 긋기·거래 취소/플랫폼 신고 = 안전.
# 요구를 받아주거나(complete_sale) 괜한 환불(accept/partial)로 넘어가면 위험.
# 기존 verdict(handled_risky/unsafe_response)를 재사용해 trust/경제/배너 처리를 그대로 탄다.
for _btype in (
    "private_contact_buyer", "romantic_pressure_buyer", "voice_phishing_buyer",
    "social_engineering_buyer", "harasser_buyer",
):
    _SELLER_VERDICT_TABLE[(_btype, "cancel_trade")] = ("handled_risky", True)
    _SELLER_VERDICT_TABLE[(_btype, "escalate_platform")] = ("handled_risky", True)
    _SELLER_VERDICT_TABLE[(_btype, "refuse_refund")] = ("handled_risky", True)
    _SELLER_VERDICT_TABLE[(_btype, "complete_sale")] = ("unsafe_response", False)
    _SELLER_VERDICT_TABLE[(_btype, "accept_refund")] = ("unsafe_response", False)
    _SELLER_VERDICT_TABLE[(_btype, "partial_refund")] = ("unsafe_response", False)

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

# 플레이어(사용자) 본인의 '거래와 무관한 사적/로맨틱/성적' 부적절 행위 감지.
# 예) "데이트해주면 반값", "사귀자", "얼굴 보여줘". 감지되면 상대(AI)를 탓하지 않고
#     '플레이어 잘못'으로 점수를 강하게 깎는다(양쪽 모드 공용).
# 주의: 정상 직거래 문구("직거래로 만나요", "역 앞에서 뵐게요", "카페 앞에서 거래")는
#       절대 오탐하면 안 된다 → '만나' 같은 모호한 어간은 넣지 않는다.
# 주의: 맨 어간("데이트","연애하","몸매")으로 부분매칭하면 '거절/상품설명'까지 오탐한다.
#   (예: "데이트하러 온 거 아니에요", "얼굴 보여드릴 수 없어요", "섹시한 느낌의 원피스")
# 그래서 '제안·요청·희망' 형태(제안자만 쓰는 표현)만 넣고, 거절/되묻기 맥락은 아래서 걸러낸다.
# 정밀도를 높여 '잘한 플레이어'를 오징계하지 않는 쪽으로 보수적으로 잡는다(재현율은 LLM 심판이 보완).
_MISCONDUCT_PHRASES = [
    # 데이트/만남 제안
    "데이트하자", "데이트 하자", "데이트해요", "데이트 해요", "데이트해주", "데이트 해주",
    "데이트하실", "데이트 하실", "데이트할래", "데이트 할래", "데이트하고 싶", "데이트 신청",
    "데이트나 하", "만나서 데이트", "데이트 어때", "데이트하면 반", "데이트해 주면",
    # 사귀자/연애 제안
    "사귀자", "사귀실래", "사귈래", "사귀고 싶", "사귀어 주", "사귀면 돼", "사귀면 반",
    "애인 하자", "애인 삼", "애인 하실", "애인 할래",
    "연애하자", "연애해요", "연애하실", "연애할래", "연애하고 싶",
    "여친 하자", "여친 할래", "남친 하자", "남친 할래", "여자친구 할래", "남자친구 할래",
    "썸 타자", "썸타자", "썸 탈래",
    # 얼굴/사진(상대에게 요청)·외모·신체 코멘트(상대 지칭)
    "얼굴 보여줘", "얼굴 보여주", "얼굴 좀 보여", "얼굴 한번 보여", "얼굴 사진 보내",
    "얼굴 사진 좀", "얼굴이 궁금", "얼굴 궁금",
    "몸매 좋으시", "몸매 좋네", "몸매가 좋", "몸매 예쁘", "몸매 보여",
    "섹시하시", "섹시하세", "섹시하네", "섹시하신", "섹시한 몸",
    "예쁘셔서", "미인이시", "미인이세", "이상형이",
]

# 거절·부정·되묻기(상대의 접근을 '당한' 쪽) 맥락이면 오탐이므로 흘려보낸다.
_MISCONDUCT_NEGATORS = [
    "아니", "안 ", "안돼", "안 돼", "못 ", "못해", "싫", "거절", "그만",
    "하지 마", "하지마", "말아", "말고", "관심 없", "필요 없",
    "는 거예요", "는 거죠", "라는 거", "라고요", "냐고", "거 아니", "라니",
]


def _detect_player_misconduct(player_text: str) -> bool:
    """플레이어 본인이 거래와 무관한 사적·로맨틱·성적 '제안/요구'를 했는지.

    상대(NPC)의 접근을 '거절'하는 정상 대응이나 상품 설명은 잡지 않는다.
    """
    # '업데이트' 같은 정상 단어가 '데이트'류로 오탐되지 않게 먼저 제거한다.
    cleaned = str(player_text or "").replace("업데이트", "")
    if not any(p in cleaned for p in _MISCONDUCT_PHRASES):
        return False
    # 거절/되묻기 맥락이 섞여 있으면(플레이어가 당한 쪽) 보수적으로 징계하지 않는다.
    if any(n in cleaned for n in _MISCONDUCT_NEGATORS):
        return False
    return True


# 플레이어 부적절 행위 코칭 (양쪽 모드 공용 — 상대가 아니라 '내 행동'을 지적).
_MISCONDUCT_COACHING = (
    "이번엔 상대가 아니라 '내 행동'이 문제였어요. 거래와 무관한 데이트·사적 요구나 "
    "외모·사생활 언급은 상대를 불쾌하게 하고 거래 자체를 무너뜨립니다. "
    "대화는 상품·가격·거래 방식에만 집중하고, 만남은 '공공장소 직거래'처럼 거래 목적으로만 잡으세요."
)


class JudgeAgent:
    # ============================================================
    #  구매자 모드 (기존)
    # ============================================================
    def evaluate(self, npc: dict, transcript: list[dict], decision: str) -> dict:
        # 1) 규칙 기반으로 정오/verdict/점수/플래그를 먼저 확정 (권위 있는 결과).
        #    (판매자 모드와 동일한 원칙 — LLM 이 점수/정답을 '상향' 좌우하지 못하게 한다.)
        base = self._evaluate_mock(npc, transcript, decision)
        # 2) 제공자가 있으면 LLM 심판으로 '표시/코칭'을 강화한다(하이브리드).
        #    LLM 은 위험신호 가산·코칭·미스컨덕트 강등만 가능 — 점수 상향/정답 뒤집기는 불가.
        if active_provider() != "mock":
            try:
                result = call_llm_json(
                    build_judge_system_prompt(),
                    [{"role": "user", "content": build_judge_user_payload(npc, transcript, decision)}],
                    use_judge_model=True,
                    temperature=0.2,
                    model=get_settings().claude_model_judge,
                )
                self._merge_llm_enrichment(base, result)
            except Exception:
                # 강화 단계 — 실패해도 규칙기반 base 를 그대로 쓴다 (게임은 멈추지 않음)
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

        # 플레이어(구매자) 본인이 거래와 무관한 사적/로맨틱/성적 요구를 했으면 '플레이어 잘못'.
        # 상대(판매자 NPC)를 탓하지 않고 점수를 매우 낮게 잡는다.
        player_text = " ".join(m["content"] for m in transcript if m["speaker"] == "player")
        misconduct = _detect_player_misconduct(player_text)
        if misconduct:
            verdict, correct = "player_misconduct", False
            score = min(score, 4)
            missed = sorted(set(missed) | {"플레이어가 거래와 무관한 사적·부적절한 요구를 함"})

        score = self._clamp_score(score)
        return {
            "verdict": verdict,
            "correct": correct,
            "score": score,
            "detected_flags": detected,
            "missed_flags": missed,
            "coaching": _MISCONDUCT_COACHING if misconduct else self._fallback_coaching(npc, decision, correct),
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
        # 2) 제공자가 있으면 LLM 심판으로 '표시/코칭'을 강화한다(하이브리드).
        if active_provider() != "mock":
            try:
                result = call_llm_json(
                    build_seller_mode_judge_system_prompt(),
                    [{"role": "user", "content": build_seller_mode_judge_user_payload(npc, transcript, decision)}],
                    use_judge_model=True,
                    temperature=0.2,
                    model=get_settings().claude_model_judge,
                )
                self._merge_llm_enrichment(base, result)
            except Exception:
                # 강화 단계 — 실패해도 규칙기반 base 를 그대로 쓴다
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
        misconduct = _detect_player_misconduct(player_text)

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

        if misconduct:
            # 플레이어(판매자) 본인이 데이트·사적/성적 요구 등 부적절 행위를 함 → 판매자 잘못.
            # 상대(AI 구매자)를 '잠수' 등으로 탓하지 않고 점수를 매우 낮게 잡는다.
            verdict, correct = "player_misconduct", False
            score = min(score, 4)
            missed = sorted(set(missed) | {"판매자가 거래와 무관한 사적·부적절한 요구를 함"})
        elif abusive:
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
            "coaching": self._seller_fallback_coaching(btype, decision, correct, abusive, misconduct),
        }

    @staticmethod
    def _seller_fallback_coaching(btype: str, decision: str, correct: bool,
                                  abusive: bool, misconduct: bool = False) -> str:
        if misconduct:
            return _MISCONDUCT_COACHING
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
            "private_contact_buyer": (
                "사적 연락 유도를 잘 막았어요. 거래·대화를 플랫폼 안에서만 유지한 게 핵심입니다.",
                "구매자가 개인 연락처·외부 메신저를 요구하면 거래 주제를 벗어난 거예요. 정중히 거절하고 플랫폼 안에서만 대화하세요.",
            ),
            "romantic_pressure_buyer": (
                "로맨틱한 접근에 선을 분명히 긋고 거래를 지킨 게 좋았어요.",
                "구매자가 로맨틱·사적인 대화를 요구하면 거래 주제를 벗어난 것입니다. 정중히 선을 긋고, 계속되면 기록을 남겨 신고·차단을 고려하세요.",
            ),
            "voice_phishing_buyer": (
                "외부 인증 요구에 응하지 않은 게 정답이에요. 개인정보는 넘기지 않는 게 안전합니다.",
                "외부 인증·통화 압박은 개인정보 노출 위험이 커요. 응하지 말고 플랫폼 공식 절차만 쓰세요.",
            ),
            "social_engineering_buyer": (
                "딱한 사정·긴박함에도 안전 절차를 지킨 게 좋았어요.",
                "감정·긴박함으로 절차를 건너뛰게 하는 압박에 말렸어요. 사정은 공감하되 기준·기록은 일관되게 지키세요.",
            ),
            "harasser_buyer": (
                "거절 후 압박에도 감정적으로 맞받지 않고 침착하게 정리한 게 좋았어요.",
                "상대가 거절 후 공격적으로 나오면 감정적으로 대응하지 말고, 기록을 남기고 신고·차단을 고려하세요.",
            ),
        }
        good, bad = msgs.get(btype, ("거래를 마무리했어요.", "다음엔 기록과 플랫폼 절차를 더 적극적으로 활용해 보세요."))
        return good if correct else bad

    # ---- 하이브리드: LLM 심판 강화 병합 (양쪽 모드 공용) ----
    def _merge_llm_enrichment(self, base: dict, result: dict) -> None:
        """규칙 기반 결과(base)에 LLM 심판의 '표시/코칭 강화'를 안전하게 병합한다.

        하이브리드 원칙 — LLM 은 점수/정오/verdict 를 절대 '상향'하지 못한다. 오직:
          (1) 규칙이 놓친 미묘한 위험 신호를 detected/missed 플래그에 '가산',
          (2) 코칭 문구를 더 자연스럽게 다듬기,
          (3) 플레이어 본인의 부적절 행위(데이트/사적·성적 요구·괴롭힘)를 잡으면 —
              키워드 규칙이 놓쳤어도 — 미스컨덕트 규칙을 트리거해 점수를 '강등만' 한다.
        (3)은 점수를 내리기만 하므로 프롬프트 인젝션으로 점수를 부풀릴 수 없다.
        """
        if not isinstance(result, dict):
            return
        # (1) 위험 신호 가산 — 규칙 결과를 앞에 두고, AI 가 새로 잡은 신호만 뒤에 붙인다(상한 8).
        for key in ("detected_flags", "missed_flags"):
            existing = base.get(key) or []
            extra = [f for f in _sanitize_flags(result.get(key)) if f not in existing]
            if extra:
                base[key] = (existing + extra)[:8]
        # (3) AI 가 플레이어 미스컨덕트를 잡으면 강등 (규칙이 이미 잡았으면 그대로 둔다).
        if _truthy(result.get("player_misconduct")) and base.get("verdict") != "player_misconduct":
            base["verdict"] = "player_misconduct"
            base["correct"] = False
            base["score"] = min(self._clamp_score(base.get("score", 0)), 4)
            tag = "플레이어가 거래와 무관한 사적·부적절한 요구를 함"
            if tag not in (base.get("missed_flags") or []):
                base["missed_flags"] = ((base.get("missed_flags") or []) + [tag])[:8]
        # (2) 코칭 — 미스컨덕트면 '플레이어 지적' 고정 코칭 유지, 아니면 AI 코칭 사용.
        if base.get("verdict") == "player_misconduct":
            base["coaching"] = _MISCONDUCT_COACHING
        else:
            coaching = sanitize_message(str(result.get("coaching", "")))
            if coaching:
                base["coaching"] = coaching

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


def _sanitize_flags(items) -> list[str]:
    """LLM 이 준 플래그 문자열을 안전하게 정리(민감정보 제거·길이 제한·개수 제한)."""
    out = []
    for s in _as_str_list(items):
        t = sanitize_message(s)[:80].strip()
        if t:
            out.append(t)
    return out[:6]


def _truthy(value) -> bool:
    """LLM 이 bool 대신 문자열('true'/'예' 등)로 줄 수 있어 관대하게 해석한다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "y", "t", "1", "참", "예")
    return bool(value)
