"""
요청/응답 모델 (Pydantic).
FastAPI 가 이 모델들로 입력값을 검증하고, 응답 형태를 보장한다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- 인증 ----------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=6, max_length=64)
    display_name: str = Field(min_length=1, max_length=20)
    email: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=64)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: int
    username: str
    display_name: str
    level: int
    xp: int
    trust_score: int
    game_role: str | None = None
    setup_completed: bool = False


# ---------- 역할 / 아바타 셋업 ----------
# 짧은 키 문자열만 받아서 프론트가 색/모양으로 매핑한다.
# pattern 으로 길이·문자 제한 → AI/사용자 입력 오염 방지.
_KEY = r"^[a-z0-9_]{1,20}$"


class AvatarConfig(BaseModel):
    skin: str = Field(default="light", pattern=_KEY)
    hat: str = Field(default="none", pattern=_KEY)
    shirt: str = Field(default="terracotta", pattern=_KEY)
    pants: str = Field(default="denim", pattern=_KEY)
    accessory: str = Field(default="none", pattern=_KEY)


class RoleSetupRequest(BaseModel):
    game_role: Literal["buyer", "seller"]
    avatar: AvatarConfig
    # 판매자 역할일 때만 의미 있음. buyer 면 무시된다.
    seller_category: str | None = Field(default=None, pattern=_KEY)


class UpdateAvatarRequest(BaseModel):
    avatar: AvatarConfig


class RoleSwitchRequest(BaseModel):
    """게임 중 역할 전환 (아바타/카테고리는 그대로 유지)."""
    game_role: Literal["buyer", "seller"]


# ---------- 마켓 선호 / 판매글 ----------
class BuyerPreferenceRequest(BaseModel):
    """구매자 모드: 오늘 찾는 물건 (위시리스트)."""
    buyer_category: str = Field(default="random", pattern=_KEY)
    buyer_price_preference: str = Field(default="fair", pattern=_KEY)
    buyer_trade_preference: str = Field(default="any", pattern=_KEY)


class EquipRequest(BaseModel):
    """인벤토리 아이템 장착."""
    item_id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_]+$")
    slot: str | None = Field(default=None, pattern=_KEY)


class UnequipRequest(BaseModel):
    """슬롯 비우기."""
    slot: str = Field(pattern=_KEY)


class SellerListingRequest(BaseModel):
    """판매자 모드: 내가 파는 물건 (판매글)."""
    category: str = Field(default="electronics", pattern=_KEY)
    product_name: str = Field(min_length=1, max_length=60)
    condition: str = Field(default="lightly_used", pattern=_KEY)
    listing_price: int = Field(default=0, ge=0, le=100_000_000)
    market_price: int = Field(default=0, ge=0, le=100_000_000)
    disclosed_defects: list[str] = Field(default_factory=list, max_length=8)
    accessories: list[str] = Field(default_factory=list, max_length=10)
    trade_methods: list[str] = Field(default_factory=list, max_length=5)
    refund_policy: str = Field(default="", max_length=200)
    proof_prepared: list[str] = Field(default_factory=list, max_length=8)


# ---------- 월드 / 위치 / 스폰 ----------
class LocationRequest(BaseModel):
    """브라우저 지오로케이션을 대략값으로만 받는다 (정밀 위치 저장 안 함)."""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    provider: str | None = Field(default=None, pattern=r"^(procedural|google|naver)$")


class SpawnResponse(BaseModel):
    """프론트로 내려보내는 단일 스폰의 공개 정보.
    role/tactics 는 물론, role 을 노출하는 npc_id 도 절대 포함하지 않는다.
    클라이언트는 spawn_instance_id 만으로 대화를 시작한다."""
    spawn_instance_id: str
    npc_kind: str
    name: str
    item_name: str
    item_category: str
    category: str
    visual_theme: str
    listing_price: int
    sprite_color: str
    x: int
    y: int
    remaining_seconds: int


# ---------- 채팅 ----------
class StartChatRequest(BaseModel):
    # 클라이언트는 보통 spawn_instance_id 만 보낸다 → 서버가 npc_id 로 매핑(정답지 보호).
    # npc_id 는 디버그/내부용 폴백으로만 허용한다.
    # 판매자 모드 인바운드 문의에서 시작할 땐 inquiry_id 만 보낸다 → 서버가 스폰으로 매핑.
    spawn_instance_id: str | None = None
    npc_id: str | None = None
    inquiry_id: str | None = None


class SendMessageRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=400)


class FlagMessageRequest(BaseModel):
    session_id: str
    message_id: int
    flagged: bool


class ResolveTradeRequest(BaseModel):
    session_id: str
    # 구매자 모드: buy | walk_away | report
    # 판매자 모드: complete_sale | refuse_refund | accept_refund |
    #             partial_refund | escalate_platform | cancel_trade
    decision: str = Field(
        pattern=r"^(buy|walk_away|report|complete_sale|refuse_refund|"
        r"accept_refund|partial_refund|escalate_platform|cancel_trade)$"
    )
    # 거래 체크리스트에서 사용자가 직접 체크한 항목 키 (선택). 올바른 결정일 때만 소폭 가점.
    checklist: list[str] = Field(default_factory=list, max_length=12)
