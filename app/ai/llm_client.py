"""
LLM 클라이언트.

OpenAI 호환 Chat Completions API 를 호출하는 얇은 래퍼.
- chat()      : 일반 대화 (판매자 에이전트가 사용, 약간 창의적이게 temperature 높음)
- chat_json() : JSON 형식 강제 응답 (판매자/심판 에이전트가 사용)

API_MODE=mock 이거나 키가 없으면 이 클라이언트는 아예 호출되지 않는다.
(그 경우 각 에이전트가 personas.py 의 mock_lines 폴백을 쓴다.)
"""
from __future__ import annotations

import json

import httpx

from app.config import get_settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.openai_base_url.rstrip("/")
        self._api_key = s.openai_api_key
        self._chat_model = s.openai_chat_model
        self._judge_model = s.openai_judge_model

    def _post(self, payload: dict) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=40.0) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()             # 비정상 본문이면 ValueError(JSONDecodeError)
            content = data["choices"][0]["message"]["content"]  # 모양 다르면 KeyError/TypeError
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
            # 어떤 형태의 응답 깨짐이든 LLMError 로 통일 → 호출부가 mock 으로 폴백
            raise LLMError(f"LLM 호출 실패: {exc}") from exc
        if content is None:
            # content: null (거부/툴콜/필터 등) → 빈 응답으로 보고 폴백
            raise LLMError("LLM 응답 content 가 null 입니다.")
        return content

    def chat_json(
        self,
        system_prompt: str,
        messages: list[dict],
        *,
        use_judge_model: bool = False,
        temperature: float = 0.7,
    ) -> dict:
        """
        JSON 객체 하나를 받아온다.
        messages 는 [{"role": "user"/"assistant", "content": "..."}] 형식의 대화 기록.
        """
        model = self._judge_model if use_judge_model else self._chat_model
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        raw = self._post(payload)
        if not isinstance(raw, str) or not raw.strip():
            raise LLMError("LLM 응답이 비어 있습니다.")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # 혹시 모델이 코드블록을 씌웠을 때 한 번 더 시도
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, TypeError) as exc:
                raise LLMError(f"JSON 파싱 실패: {raw[:200]}") from exc


# 앱 전체에서 하나만 쓰면 충분하다.
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
