"""
하위호환 shim.

판매자 에이전트 구현은 app/ai/roleplay.py 로 옮겼다 (BuyerAgent 와 공용 베이스 공유).
기존 import 경로(`from app.ai.seller_agent import SellerAgent`)를 깨지 않기 위해
여기서 그대로 재노출한다.
"""
from __future__ import annotations

from app.ai.roleplay import BaseRoleplayAgent, BuyerAgent, SellerAgent

__all__ = ["SellerAgent", "BuyerAgent", "BaseRoleplayAgent"]
