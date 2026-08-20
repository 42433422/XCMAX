"""Java wallet adapter used by LLM settlement."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, cast

import httpx
from fastapi import HTTPException

from modstore_server.application.payment_gateway import PaymentGatewayService
from modstore_server.llm_billing_values import WalletHold, money, money_str


class JavaWalletClient:
    def __init__(self):
        self.gateway = PaymentGatewayService()

    @property
    def enabled(self) -> bool:
        return cast(str, self.gateway.backend) == "java"

    async def preauthorize(
        self,
        authorization: str,
        amount: Decimal,
        provider: str,
        model: str,
        request_id: str,
    ) -> WalletHold:
        if not self.enabled:
            return WalletHold(hold_no=f"debug-{request_id}", amount=money(amount), enabled=False)
        data = await self._post(
            "/api/wallet/ai/preauthorize",
            authorization,
            {
                "amount": money_str(amount),
                "provider": provider,
                "model": model,
                "request_id": request_id,
                "idempotency_key": f"{request_id}:preauth",
            },
        )
        hold = data.get("hold") or {}
        return WalletHold(
            hold_no=str(hold.get("hold_no") or ""),
            amount=money(hold.get("amount") or amount),
            enabled=True,
        )

    async def settle(
        self,
        authorization: str,
        hold: WalletHold,
        actual_amount: Decimal,
        request_id: str,
    ) -> None:
        if hold.enabled:
            await self._post(
                "/api/wallet/ai/settle",
                authorization,
                {
                    "hold_no": hold.hold_no,
                    "actual_amount": money_str(actual_amount),
                    "idempotency_key": f"{request_id}:settle",
                },
            )

    async def release(
        self, authorization: str, hold: WalletHold, reason: str, request_id: str
    ) -> None:
        if hold.enabled:
            await self._post(
                "/api/wallet/ai/release",
                authorization,
                {
                    "hold_no": hold.hold_no,
                    "reason": reason,
                    "idempotency_key": f"{request_id}:release",
                },
            )

    async def _post(self, path: str, authorization: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if not authorization:
            raise HTTPException(401, "缺少登录令牌，无法完成钱包扣费")
        from modstore_server.infrastructure.http_clients import get_java_client

        try:
            response = await get_java_client().post(
                f"{self.gateway.target_base_url()}{path}",
                headers={
                    "Authorization": authorization,
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=20.0,
            )
        except httpx.HTTPError as error:
            from modstore_server.application.payment_gateway import (
                java_payment_unreachable_message,
            )

            raise HTTPException(502, java_payment_unreachable_message(error)) from error
        if response.status_code >= 400:
            raise HTTPException(response.status_code, response.text[:500])
        data = response.json()
        if data.get("ok") is False:
            message = str(data.get("message") or "钱包扣费失败")
            if "余额不足" in message:
                raise HTTPException(402, message)
            raise HTTPException(503, message)
        return cast(dict[str, Any], data)
