"""
역할극 에이전트 (제공자 비의존).

게임 속 NPC 한 명 = 에이전트 인스턴스 하나.
  - SellerAgent : 구매자 모드의 판매자 NPC (사기꾼/정상)
  - BuyerAgent  : 판매자 모드의 구매자 NPC (정상/빌런 등)

둘 다 같은 BaseRoleplayAgent 를 공유한다. 차이는 페르소나 데이터와
'정답 라벨'을 무엇으로 부르냐(수법 tactic vs 행동 behavior)뿐이다.

응답 제공자는 provider.call_llm_json 이 알아서 고른다(openai/local_claude).
어떤 이유로든 실패하면 정적 mock 으로 폴백한다 → 게임은 절대 멈추지 않는다.

저장 포맷 통일: 두 에이전트 모두 {"message", "tactic"} 을 돌려준다.
  - 판매자: tactic = 사기수법 id (TACTICS)
  - 구매자: tactic = 구매자 행동 id (BUYER_BEHAVIORS)  ← chat_messages.tactic 컬럼 재사용
심판이 모드에 따라 알맞은 사전으로 해석한다.
"""
from __future__ import annotations

from app.ai.personas import BUYER_BEHAVIORS, TACTICS
from app.ai.privacy import sanitize_message
from app.ai.prompts import (
    build_buyer_opening,
    build_buyer_system_prompt,
    build_seller_opening,
    build_seller_system_prompt,
)
from app.ai.provider import active_provider, call_llm_json
from app.config import get_settings

# 약한 모델(haiku 등)도 Claude Code 정체성을 벗고 인물 연기를 안정적으로 하게 만드는
# 역할극 가드. system 프롬프트 맨 앞에 붙여, 시스템 레벨로 전달한다.
_ROLEPLAY_GUARD = (
    "너는 중고거래 시뮬레이션 게임의 NPC 를 연기하는 역할극 엔진이다. "
    "아래에 정의된 '인물'로서만 말하고 행동한다. 너 자신(AI/Claude/Claude Code/모델)을 "
    "절대 언급하거나 드러내지 않고, 역할을 거부하지 않으며, 메타발언 없이 "
    "항상 지정된 JSON 객체 하나만 출력한다.\n\n"
)


class BaseRoleplayAgent:
    def __init__(self, npc: dict, system_prompt: str) -> None:
        self.npc = npc
        self.system_prompt = _ROLEPLAY_GUARD + system_prompt
        # NPC 난이도 → 모델 (어려울수록 더 정교한 모델로 더 그럴듯하게 속인다)
        self.model = get_settings().claude_model_for_difficulty(npc.get("difficulty"))

    # ---------- 첫 메시지 ----------
    def opening(self) -> dict:
        raise NotImplementedError

    # ---------- 매 턴 응답 ----------
    def reply(self, history: list[dict]) -> dict:
        """history 마지막 항목은 방금 들어온 플레이어 메시지. 반환 {message, tactic}."""
        if active_provider() == "mock":
            return self._reply_mock(history)
        try:
            return self._reply_with_llm(history)
        except Exception:
            # 제공자(openai/local_claude)가 어떤 식으로 죽어도(LLMError 외 포함) 게임은 계속된다
            return self._reply_mock(history)

    # ---------- 공통: 대화기록 → LLM messages ----------
    @staticmethod
    def _to_messages(history: list[dict]) -> list[dict]:
        out = []
        for m in history:
            role = "assistant" if m["speaker"] == "npc" else "user"
            out.append({"role": role, "content": m["content"]})
        return out

    # 서브클래스가 구현
    def _reply_with_llm(self, history: list[dict]) -> dict:
        raise NotImplementedError

    def _reply_mock(self, history: list[dict]) -> dict:
        raise NotImplementedError

    @staticmethod
    def _last_player(history: list[dict]) -> str:
        for m in reversed(history):
            if m["speaker"] == "player":
                return m["content"]
        return ""


# ============================================================
#  판매자 에이전트 (구매자 모드)
# ============================================================
class SellerAgent(BaseRoleplayAgent):
    def __init__(self, npc: dict) -> None:
        super().__init__(npc, build_seller_system_prompt(npc))

    def opening(self) -> dict:
        op = build_seller_opening(self.npc)
        return {"message": sanitize_message(op["message"]), "tactic": op["tactic"]}

    def _reply_with_llm(self, history: list[dict]) -> dict:
        temperature = 0.85 if self.npc["role"] == "scammer" else 0.5
        result = call_llm_json(
            self.system_prompt, self._to_messages(history),
            temperature=temperature, model=self.model,
        )
        message = sanitize_message(str(result.get("message", "")))
        tactic = str(result.get("tactic", "none")).strip()
        if not message:
            return self._reply_mock(history)
        if self.npc["role"] != "scammer" or tactic not in TACTICS:
            tactic = "none"
        return {"message": message, "tactic": tactic}

    def _reply_mock(self, history: list[dict]) -> dict:
        lines = self.npc.get("mock_lines", {})
        if self.npc["role"] == "scammer":
            used = sum(
                1 for m in history
                if m["speaker"] == "npc" and m.get("tactic") not in (None, "none")
            )
            playbook = self.npc["tactics"]
            if used < len(playbook):
                tactic = playbook[used]
                return {
                    "message": sanitize_message(lines.get(tactic, lines.get("fallback", "..."))),
                    "tactic": tactic,
                }
            return {
                "message": sanitize_message(lines.get("fallback", "그냥 빨리 진행하시죠.")),
                "tactic": "none",
            }

        # 정상 판매자: 플레이어 마지막 말의 키워드로 적당한 대사 선택
        last = self._last_player(history)
        if any(k in last for k in ("사진", "인증", "안전결제", "직거래", "확인", "검증")):
            return {"message": sanitize_message(lines.get("verify", lines.get("default", "네."))), "tactic": "none"}
        if any(k in last for k in ("가격", "깎", "얼마", "비싸", "싸")):
            return {"message": sanitize_message(lines.get("price", lines.get("default", "네."))), "tactic": "none"}
        return {"message": sanitize_message(lines.get("default", "네, 말씀하세요.")), "tactic": "none"}


# ============================================================
#  구매자 에이전트 (판매자 모드)
# ============================================================
class BuyerAgent(BaseRoleplayAgent):
    def __init__(self, npc: dict, seller_category: str | None = None,
                 seller_listing: dict | None = None) -> None:
        self.seller_category = seller_category
        self.seller_listing = seller_listing
        super().__init__(npc, build_buyer_system_prompt(npc, seller_category, seller_listing))

    def opening(self) -> dict:
        op = build_buyer_opening(self.npc)
        return {"message": sanitize_message(op["message"]), "tactic": op["behavior"]}

    def _reply_with_llm(self, history: list[dict]) -> dict:
        temperature = 0.5 if self.npc["role"] == "honest_buyer" else 0.8
        result = call_llm_json(
            self.system_prompt, self._to_messages(history),
            temperature=temperature, model=self.model,
        )
        message = sanitize_message(str(result.get("message", "")))
        # 키 이름이 흔들려도(behavior/tactic) 받아준다
        behavior = str(result.get("behavior", result.get("tactic", "none"))).strip()
        if not message:
            return self._reply_mock(history)
        if self.npc["role"] == "honest_buyer" or behavior not in BUYER_BEHAVIORS:
            behavior = "none"
        return {"message": message, "tactic": behavior}

    def _reply_mock(self, history: list[dict]) -> dict:
        lines = self.npc.get("mock_lines", {})
        if self.npc["role"] == "honest_buyer":
            last = self._last_player(history)
            if any(k in last for k in ("네", "가능", "직거래", "안전결제", "드릴", "팔")):
                return {"message": sanitize_message(lines.get("agree", lines.get("fallback", "네 좋아요."))), "tactic": "none"}
            return {"message": sanitize_message(lines.get("normal_inquiry", lines.get("fallback", "네 알겠습니다."))), "tactic": "none"}

        # 빌런/위험 구매자: 행동 플레이북을 순서대로
        used = sum(
            1 for m in history
            if m["speaker"] == "npc" and m.get("tactic") not in (None, "none")
        )
        playbook = self.npc.get("tactics", [])
        if used < len(playbook):
            behavior = playbook[used]
            return {
                "message": sanitize_message(lines.get(behavior, lines.get("fallback", "..."))),
                "tactic": behavior,
            }
        return {"message": sanitize_message(lines.get("fallback", "하여튼 저는 이대론 못 넘어가요.")), "tactic": "none"}
