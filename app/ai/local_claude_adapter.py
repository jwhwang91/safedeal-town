"""
로컬 Claude Code(또는 호환 CLI) 어댑터 — 개인 로컬 사용 전용.

목적:
  API 키 없이도, 내 PC 에 깔린 Claude Code 같은 로컬 CLI 를 subprocess 로 불러
  NPC 대사/판정을 '진짜 LLM' 으로 받아보고 싶을 때 쓴다.

설계 원칙 (안전 최우선):
  - 특정 CLI 명령을 하드코딩하지 않는다. 전부 환경변수로 설정한다.
      CLAUDE_CODE_COMMAND   (기본: "claude")
      CLAUDE_CODE_ARGS      (기본: "" — 공백으로 분리, "{prompt}" 자리표시자 지원)
      CLAUDE_CODE_TIMEOUT_SECONDS (기본: 60)
  - shell=True 를 쓰지 않는다 (명령 주입 방지). 인자는 리스트로 넘긴다.
  - JSON 출력을 요청하고, 방어적으로 파싱한다 (코드블록/잡텍스트 제거).
  - 출력 길이를 제한하고, 필드를 문자열로 강제(sanitize)한다.
  - 타임아웃/실패/명령없음 → 전부 LLMError 로 올려서, 호출부가 정적 mock 으로 폴백한다.

이 어댑터는 AI_MODE=local_claude 일 때만 호출된다. 그 외에는 아예 안 불린다.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess

from app.ai.llm_client import LLMError
from app.config import get_settings

_MAX_OUTPUT_CHARS = 20_000   # 로컬 CLI 가 폭주해도 메모리 방어
_MAX_MESSAGE_CHARS = 600     # NPC 한 마디 최대 길이


def _build_prompt(system_prompt: str, messages: list[dict]) -> str:
    """system + 대화기록을 하나의 텍스트 프롬프트로 합친다 ({prompt} 자리표시자 모드용)."""
    parts = [system_prompt.strip(), "", "=== 지금까지의 대화 ==="]
    if not messages:
        parts.append("(아직 대화 없음 — 너가 먼저 자연스럽게 말을 건다)")
    for m in messages:
        tag = "나" if m.get("role") == "assistant" else "상대"
        parts.append(f"{tag}: {str(m.get('content', '')).strip()}")
    parts.append("")
    parts.append(
        "위 대화에 이어, 시스템 지시에 정의된 JSON 객체 '하나만' 출력해라. "
        "코드블록(```)이나 설명 문장은 절대 붙이지 마라."
    )
    return "\n".join(parts)


def _build_user_prompt(messages: list[dict]) -> str:
    """대화 기록만 사용자 프롬프트로 만든다 (인물 지시는 --append-system-prompt 로 따로 전달)."""
    parts = ["=== 지금까지의 대화 ==="]
    if not messages:
        parts.append("(아직 대화 없음 — 너가 먼저 자연스럽게 말을 건다)")
    for m in messages:
        tag = "나" if m.get("role") == "assistant" else "상대"
        parts.append(f"{tag}: {str(m.get('content', '')).strip()}")
    parts.append("")
    parts.append(
        "위 대화에 이어, 시스템 지시(인물 설정)에 정의된 JSON 객체 '하나만' 출력해라. "
        "코드블록(```)이나 설명 문장은 절대 붙이지 마라."
    )
    return "\n".join(parts)


def _extract_json(raw: str) -> dict:
    """잡텍스트 속에서 첫 JSON 객체를 최대한 건져낸다."""
    text = raw.strip()
    # 코드블록 제거
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 본문에서 첫 '{' ~ 짝 맞는 '}' 구간을 탐색
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start:i + 1]
                    try:
                        return json.loads(chunk)
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"local_claude JSON 파싱 실패: {raw[:200]!r}")


def _sanitize(obj: dict) -> dict:
    """필드를 문자열로 강제하고 길이를 자른다. 알 수 없는 키는 통과시킨다."""
    out = dict(obj) if isinstance(obj, dict) else {}
    if "message" in out:
        msg = str(out.get("message", "")).strip()
        # 제어문자 정리 + 길이 제한
        msg = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", msg)
        out["message"] = msg[:_MAX_MESSAGE_CHARS]
    return out


def _terminate_tree(proc: subprocess.Popen) -> None:
    """자식뿐 아니라 손자 프로세스까지 확실히 죽인다 (stdout 파이프를 손자가 잡고 있어도 멈추지 않게)."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run(cmd: list[str], stdin_data: str | None, timeout: int):
    """프로세스 그룹/트리 단위로 실행하고, 타임아웃이면 트리째 죽인다. (rc, stdout, stderr)."""
    popen_kw: dict = {}
    if os.name == "nt":
        # Windows: 새 프로세스 그룹 → 트리 종료(taskkill /T) 가능
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # POSIX: 새 세션 → killpg 로 손자까지 정리
        popen_kw["start_new_session"] = True

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kw,
    )
    try:
        out, err = proc.communicate(input=stdin_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_tree(proc)
        # 트리를 죽였으니 파이프가 닫혀 communicate 가 곧 반환된다 (영구 hang 방지)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        raise LLMError("로컬 명령 타임아웃")
    return proc.returncode, out, err


def run_json(
    system_prompt: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    model: str | None = None,
) -> dict:
    """
    로컬 CLI 를 한 번 호출해서 JSON dict 를 돌려준다.
    실패하면 LLMError 를 던진다 (호출부가 mock 으로 폴백).
    temperature 는 generic CLI 에 일반적으로 안 먹으므로 무시될 수 있다(시그니처 호환용).
    model 은 기본(stdin) 모드에서만 `--model <model>` 로 적용된다. CLAUDE_CODE_ARGS 에
    "{prompt}" 자리표시자를 쓰는 범용 모드에서는 모델 선택이 인자에 직접 들어가야 하며
    여기서 자동 추가하지 않는다(사용자 인자와의 충돌 방지).
    """
    s = get_settings()
    command = s.claude_code_command.strip()
    if not command:
        raise LLMError("CLAUDE_CODE_COMMAND 가 비어 있음")

    # 따옴표 짝이 안 맞는 등 CLAUDE_CODE_ARGS 가 깨져 있어도 LLMError 로 떨궈 mock 폴백.
    try:
        extra = shlex.split(s.claude_code_args) if s.claude_code_args else []
    except ValueError as exc:
        raise LLMError(f"CLAUDE_CODE_ARGS 파싱 실패: {exc}") from exc

    if any("{prompt}" in a for a in extra):
        # 범용 모드: 인물 지시 + 대화를 한 프롬프트로 합쳐 자리표시자에 끼워넣는다.
        full = _build_prompt(system_prompt, messages)
        cmd = [command] + [a.replace("{prompt}", full) for a in extra]
        stdin_data: str | None = None
    else:
        # claude 모드: 인물 지시는 시스템 프롬프트로(--append-system-prompt),
        # 대화는 stdin 으로 전달한다. 시스템 레벨로 줘야 약한 모델(haiku)도
        # Claude Code 정체성을 벗고 인물 연기를 안정적으로 한다.
        cmd = [command] + extra
        if model:
            cmd += ["--model", model]
        sys_text = (system_prompt or "").strip()
        if sys_text:
            cmd += ["--append-system-prompt", sys_text]
        stdin_data = _build_user_prompt(messages)

    try:
        rc, out, err = _run(cmd, stdin_data, max(5, s.claude_code_timeout_seconds))
    except FileNotFoundError as exc:
        raise LLMError(f"로컬 명령을 찾을 수 없음: {command}") from exc
    except OSError as exc:
        raise LLMError(f"로컬 명령 실행 실패: {exc}") from exc

    if rc != 0:
        raise LLMError(f"로컬 명령 비정상 종료(code={rc}): {(err or '')[:200]}")

    raw = (out or "")[:_MAX_OUTPUT_CHARS]
    if not raw.strip():
        raise LLMError("로컬 명령 출력이 비어 있음")

    return _sanitize(_extract_json(raw))
