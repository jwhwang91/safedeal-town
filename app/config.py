"""
설정 로더.
.env 파일을 읽어서 앱 전체에서 쓰는 Settings 객체 하나로 만들어 둔다.
복잡한 라이브러리 없이, 그냥 환경변수만 깔끔하게 모은다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 (이 파일 기준 한 칸 위)
BASE_DIR = Path(__file__).resolve().parent.parent

# .env 가 있으면 읽어들인다. 없어도 그냥 기본값으로 굴러간다.
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    return _get(name, "true" if default else "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


@dataclass(frozen=True)
class Settings:
    # AI
    ai_mode: str                 # "mock" | "openai" | "local_claude"
    openai_api_key: str
    openai_base_url: str
    openai_chat_model: str
    openai_judge_model: str

    # 로컬 Claude Code(또는 호환 CLI) 어댑터 — 개인 로컬 사용 전용
    claude_code_command: str
    claude_code_args: str
    claude_code_timeout_seconds: int

    # NPC 난이도별 모델 (어려울수록 더 정교한 모델로 더 그럴듯하게 속이도록)
    claude_model_easy: str
    claude_model_medium: str
    claude_model_hard: str
    claude_model_judge: str

    # 맵 제공자
    map_provider: str            # "procedural" | "google" | "naver"
    google_maps_api_key: str
    naver_map_client_id: str
    naver_map_client_secret: str

    # 시장 데이터 제공자 (동적 매물 생성용)
    # "synthetic" | "manual_import" | "trend_cache" | "official_stub"
    market_listing_provider: str
    market_import_path: Path
    market_trend_cache_path: Path
    allow_experimental_market_providers: bool

    # 적응형 시나리오 엔진 (방어 훈련 커리큘럼 — 사기 생성 아님)
    adaptive_scenarios_enabled: bool
    store_redacted_transcripts: bool
    persona_evolution_provider: str       # "template" | "local_claude" | "openai"
    adaptive_min_history_for_personalization: int
    adaptive_recent_avoid_window_days: int
    adaptive_debug_explain: bool

    # 동적 페르소나 생성 (스폰 시점에 local_claude/openai 로 페르소나 JSON 을 생성)
    # 기존 적응형 변주(persona_evolution_provider)와는 별개의 레이어다.
    #   - template     : 내장 템플릿만 사용 (기본값, 항상 안전/오프라인)
    #   - local_claude : 로컬 CLI 로 매번 다른 페르소나 생성 (실패 시 template 폴백)
    #   - openai       : OpenAI 호환 API 로 생성 (실패 시 template 폴백)
    dynamic_persona_provider: str
    dynamic_persona_cache: bool
    dynamic_persona_cache_ttl_minutes: int

    # 상품 카탈로그 신선도: 모델 연식 생성의 상한 기준 연도 (없으면 서버 날짜에서 도출)
    current_market_year: int

    # 판매자 모드 인바운드 문의 페이싱 (구매자 NPC 가 하나둘 문의를 보낸다)
    seller_inquiry_min_delay_seconds: int
    seller_inquiry_max_delay_seconds: int
    seller_max_pending_inquiries: int
    seller_max_approaching_buyers: int

    # 서버
    host: str
    port: int

    # 보안
    jwt_secret: str
    password_pepper: str
    token_ttl_minutes: int

    # DB
    database_path: Path

    @property
    def use_openai(self) -> bool:
        """openai 모드이고 키가 실제로 들어있을 때만 진짜 API를 쓴다."""
        return self.ai_mode.lower() == "openai" and bool(self.openai_api_key.strip())

    @property
    def ai_provider(self) -> str:
        """
        실제로 쓸 AI 제공자를 하나로 정리해서 돌려준다.
          - "openai"        : openai 모드 + 키 있음
          - "local_claude"  : local_claude 모드 (CLI 가 없으면 호출 시 mock 으로 폴백)
          - "mock"          : 그 외 전부 (키 없는 openai, 기본값 등)
        에이전트들은 이 값만 보고 분기하면 된다.
        """
        mode = self.ai_mode.lower()
        if mode == "openai" and bool(self.openai_api_key.strip()):
            return "openai"
        if mode == "local_claude":
            return "local_claude"
        return "mock"

    def claude_model_for_difficulty(self, difficulty: str | None) -> str:
        """NPC 난이도 → Claude 모델 별칭. 어려울수록 더 강한 모델."""
        return {
            "hard": self.claude_model_hard,
            "medium": self.claude_model_medium,
            "easy": self.claude_model_easy,
        }.get((difficulty or "medium").lower(), self.claude_model_medium)

    @property
    def adaptive_provider_effective(self) -> str:
        """페르소나 진화 제공자를 정규화한다.

        허용값(template/local_claude/openai) 외에는 안전 기본값 template 로 떨어뜨린다.
        local_claude/openai 라도 실제 생성에 실패하면 호출부가 template 로 폴백하므로
        게임은 절대 멈추지 않는다.
        """
        p = (self.persona_evolution_provider or "template").strip().lower()
        return p if p in ("template", "local_claude", "openai") else "template"

    @property
    def dynamic_persona_provider_effective(self) -> str:
        """스폰 시점 동적 페르소나 제공자를 정규화한다.

        허용값(template/local_claude/openai) 외에는 안전 기본값 template 로 떨어뜨린다.
        local_claude/openai 라도 실제 생성/검증에 실패하면 호출부가 template 로 폴백하므로
        게임은 절대 멈추지 않는다. (적응형 persona_evolution_provider 와는 독립적인 설정.)
        """
        p = (self.dynamic_persona_provider or "template").strip().lower()
        return p if p in ("template", "local_claude", "openai") else "template"

    @property
    def map_provider_effective(self) -> str:
        """
        키가 없는 google/naver 는 무조건 procedural 로 떨어뜨린다.
        (키 없이도 앱이 항상 돌아가야 하므로)
        """
        p = self.map_provider.lower()
        if p == "google" and self.google_maps_api_key.strip():
            return "google"
        if p == "naver" and self.naver_map_client_id.strip():
            return "naver"
        return "procedural"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    db_path = Path(_get("DATABASE_PATH", "runtime/safedeal_town.sqlite3"))
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    import_path = Path(_get("MARKET_IMPORT_PATH", "runtime/imports/market_listings.json"))
    if not import_path.is_absolute():
        import_path = BASE_DIR / import_path
    trend_path = Path(_get("MARKET_TREND_CACHE_PATH", "runtime/market_trends.json"))
    if not trend_path.is_absolute():
        trend_path = BASE_DIR / trend_path

    return Settings(
        ai_mode=_get("AI_MODE", "mock"),
        openai_api_key=_get("OPENAI_API_KEY", ""),
        openai_base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_chat_model=_get("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        openai_judge_model=_get("OPENAI_JUDGE_MODEL", "gpt-4o-mini"),
        claude_code_command=_get("CLAUDE_CODE_COMMAND", "claude"),
        claude_code_args=_get("CLAUDE_CODE_ARGS", ""),
        claude_code_timeout_seconds=_get_int("CLAUDE_CODE_TIMEOUT_SECONDS", 60),
        # 난이도별 모델 기본값은 정확한 ID 로 못박는다(별칭 "opus/sonnet/haiku" 도 CLI 가 받지만,
        # 버전이 바뀌어도 의도한 모델이 쓰이도록 ID 고정). 어려울수록 더 강한 모델로 더 정교하게 속인다.
        claude_model_easy=_get("CLAUDE_MODEL_EASY", "claude-haiku-4-5-20251001"),
        claude_model_medium=_get("CLAUDE_MODEL_MEDIUM", "claude-sonnet-4-6"),
        claude_model_hard=_get("CLAUDE_MODEL_HARD", "claude-opus-4-8"),
        claude_model_judge=_get("CLAUDE_MODEL_JUDGE", "claude-haiku-4-5-20251001"),
        map_provider=_get("MAP_PROVIDER", "procedural"),
        google_maps_api_key=_get("GOOGLE_MAPS_API_KEY", ""),
        naver_map_client_id=_get("NAVER_MAP_CLIENT_ID", ""),
        naver_map_client_secret=_get("NAVER_MAP_CLIENT_SECRET", ""),
        market_listing_provider=_get("MARKET_LISTING_PROVIDER", "synthetic"),
        market_import_path=import_path,
        market_trend_cache_path=trend_path,
        allow_experimental_market_providers=_get_bool(
            "ALLOW_EXPERIMENTAL_MARKET_PROVIDERS", False
        ),
        adaptive_scenarios_enabled=_get_bool("ADAPTIVE_SCENARIOS_ENABLED", True),
        store_redacted_transcripts=_get_bool("STORE_REDACTED_TRANSCRIPTS", False),
        persona_evolution_provider=_get("PERSONA_EVOLUTION_PROVIDER", "template"),
        adaptive_min_history_for_personalization=_get_int(
            "ADAPTIVE_MIN_HISTORY_FOR_PERSONALIZATION", 3
        ),
        adaptive_recent_avoid_window_days=_get_int(
            "ADAPTIVE_RECENT_AVOID_WINDOW_DAYS", 7
        ),
        adaptive_debug_explain=_get_bool("ADAPTIVE_DEBUG_EXPLAIN", False),
        dynamic_persona_provider=_get("DYNAMIC_PERSONA_PROVIDER", "template"),
        dynamic_persona_cache=_get_bool("DYNAMIC_PERSONA_CACHE", True),
        dynamic_persona_cache_ttl_minutes=_get_int(
            "DYNAMIC_PERSONA_CACHE_TTL_MINUTES", 120
        ),
        # 0/미설정이면 호출부가 서버의 현재 연도를 쓴다 (날짜 인지 카탈로그).
        current_market_year=_get_int("CURRENT_MARKET_YEAR", 0),
        seller_inquiry_min_delay_seconds=_get_int(
            "SELLER_INQUIRY_MIN_DELAY_SECONDS", 15
        ),
        seller_inquiry_max_delay_seconds=_get_int(
            "SELLER_INQUIRY_MAX_DELAY_SECONDS", 45
        ),
        seller_max_pending_inquiries=_get_int("SELLER_MAX_PENDING_INQUIRIES", 3),
        seller_max_approaching_buyers=_get_int("SELLER_MAX_APPROACHING_BUYERS", 2),
        host=_get("HOST", "0.0.0.0"),
        port=_get_int("PORT", 8000),
        jwt_secret=_get("JWT_SECRET", "dev-insecure-secret-change-me"),
        password_pepper=_get("PASSWORD_PEPPER", "dev-insecure-pepper-change-me"),
        token_ttl_minutes=_get_int("TOKEN_TTL_MINUTES", 720),
        database_path=db_path,
    )
