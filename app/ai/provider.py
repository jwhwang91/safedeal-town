"""
제공자 비의존(provider-agnostic) AI 호출 계층.

채팅 UI 와 에이전트는 "응답이 어디서 왔는지" 몰라도 된다.
여기서 AI_MODE 에 따라 실제 백엔드를 고른다:

  - openai        : OpenAI 호환 Chat Completions (llm_client)
  - local_claude  : 로컬 Claude Code/호환 CLI (local_claude_adapter)
  - 그 외(mock)   : LLMError 를 던져서 호출부가 정적 mock 으로 폴백하게 함

새 제공자(GPT/Gemini/Claude 공식 API 등)를 나중에 붙일 때도
이 함수 하나에 분기만 추가하면 된다.
"""
from __future__ import annotations

from app.ai.llm_client import LLMError, get_llm_client
from app.config import get_settings


def call_llm_json(
    system_prompt: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    use_judge_model: bool = False,
    model: str | None = None,
) -> dict:
    """현재 설정된 제공자로 JSON 응답 하나를 받아온다. mock 이면 LLMError.

    model: local_claude 모드에서 NPC 난이도별 모델(opus/sonnet/haiku)을 고를 때 쓴다.
    """
    provider = get_settings().ai_provider

    if provider == "openai":
        return get_llm_client().chat_json(
            system_prompt, messages,
            use_judge_model=use_judge_model, temperature=temperature,
        )

    if provider == "local_claude":
        # 늦은 import: 로컬 모드가 아닐 땐 subprocess 모듈 경로를 건드리지 않는다.
        from app.ai import local_claude_adapter
        return local_claude_adapter.run_json(
            system_prompt, messages, temperature=temperature, model=model
        )

    raise LLMError("AI 제공자가 설정되지 않음(mock) — 정적 폴백 사용")


def active_provider() -> str:
    return get_settings().ai_provider
