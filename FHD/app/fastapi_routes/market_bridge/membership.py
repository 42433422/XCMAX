"""Optional membership reads and public plan fallback policy."""

from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .ports import ProxyJSON


@dataclass
class Membership:
    proxy: ProxyJSON
    logger: Logger

    async def tier(self, market_token: str) -> str | None:
        """登录后从修茈市场拉取当前用户会员等级 tier（free/vip/vip_plus/svip1..8）。

        市场登录响应不含会员等级，需单独调 ``GET /api/payment/my-plan``。
        任何失败均返回 None（不阻断登录）。
        """
        token = (market_token or "").strip()
        if not token:
            return None
        try:
            data = await self.proxy(
                "GET", "/api/payment/my-plan", authorization=token, return_error_payload=True
            )
        except RECOVERABLE_ERRORS:
            self.logger.warning("fetch_market_membership_tier 调用失败", exc_info=True)
            return None
        if not isinstance(data, dict) or data.get("__proxy_error__"):
            return None
        membership = data.get("membership")
        if isinstance(membership, dict):
            tier = str(membership.get("tier") or "").strip()
            return tier or None
        return None

    async def plans(self) -> Any:
        """会员套餐列表（代理市场公开接口 ``GET /api/payment/plans``）。

        供 ModelPaymentView 读取，替代前端硬编码；市场不可达时返回空列表，前端用本地 FALLBACK。
        """
        data = await self.proxy("GET", "/api/payment/plans", return_error_payload=True)
        if isinstance(data, dict) and (not data.get("__proxy_error__")):
            plans = data.get("plans")
            return {"success": True, "data": {"plans": plans if isinstance(plans, list) else []}}
        return {"success": True, "data": {"plans": []}}
