"""Java wallet adapter used by LLM settlement."""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from typing import Any, Dict, cast

import httpx
import jwt
from fastapi import HTTPException, Request

from modstore_server.application.payment_gateway import PaymentGatewayService
from modstore_server.llm_billing_values import WalletHold, money, money_str


class JavaWalletClient:
    def __init__(self, request: Request | None = None):
        self.gateway = PaymentGatewayService()
        self.request = request

    def _is_pat(self) -> bool:
        return (
            self.request is not None
            and getattr(self.request.state, "llm_pat_user_id", None) is not None
        )

    @property
    def enabled(self) -> bool:
        return cast(str, self.gateway.backend) == "java"

    def validate_pat(self, authorization: str) -> None:
        """Accept an in-flight model operation only after fresh scoped authentication."""
        if not self._is_pat():
            return
        from modstore_server.auth_service import PAT_PREFIX, resolve_pat_identity

        raw = authorization.strip()
        token = raw[7:].strip() if raw.startswith("Bearer ") else ""
        identity = resolve_pat_identity(token) if token.startswith(PAT_PREFIX) else None
        if (
            not identity
            or str(identity.user.account_state or "").strip().lower()
            in {"deleted", "disabled", "suspended", "blocked"}
            or "llm:use" not in identity.scopes
            or int(identity.user.id) != self.request.state.llm_pat_user_id
        ):
            raise HTTPException(401, "凭证无效或已过期")

    async def preauthorize(
        self,
        authorization: str,
        amount: Decimal,
        provider: str,
        model: str,
        request_id: str,
    ) -> WalletHold:
        self.validate_pat(authorization)
        if not self.enabled:
            if self._is_pat():
                raise HTTPException(503, "模型密钥计费服务未配置")
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
        if self._is_pat():
            try:
                received = Decimal(str(hold.get("amount"))) if isinstance(hold, dict) else None
                if (
                    not isinstance(hold, dict)
                    or not isinstance(hold.get("hold_no"), str)
                    or not hold.get("hold_no")
                    or len(hold["hold_no"]) > 64
                    or hold.get("status") != "held"
                    or received is None
                    or not received.is_finite()
                    or received.as_tuple().exponent < -2
                    or received != money(amount)
                ):
                    raise ValueError("invalid hold")
            except (TypeError, ValueError, ArithmeticError) as exc:
                raise HTTPException(502, "模型预授权响应无效") from exc
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
            body = {
                "hold_no": hold.hold_no,
                "actual_amount": money_str(actual_amount),
                "idempotency_key": f"{request_id}:settle",
            }
            if self._is_pat():
                body["request_id"] = request_id
            data = await self._post(
                "/api/wallet/ai/settle",
                authorization,
                body,
            )
            if self._is_pat():
                try:
                    result = data.get("hold")
                    actual = (
                        Decimal(str(result.get("settled_amount")))
                        if isinstance(result, dict)
                        else None
                    )
                    if (
                        not isinstance(result, dict)
                        or result.get("hold_no") != hold.hold_no
                        or result.get("status") != "settled"
                        or actual is None
                        or not actual.is_finite()
                        or actual.as_tuple().exponent < -2
                        or actual != money(actual_amount)
                    ):
                        raise ValueError("invalid settlement")
                except (TypeError, ValueError, ArithmeticError) as exc:
                    raise HTTPException(502, "模型结算响应无效") from exc

    async def release(
        self, authorization: str, hold: WalletHold, reason: str, request_id: str
    ) -> None:
        if hold.enabled:
            body = {
                "hold_no": hold.hold_no,
                "reason": reason,
                "idempotency_key": f"{request_id}:release",
            }
            if self._is_pat():
                body["request_id"] = request_id
                body["reason"] = (reason or "upstream error")[:256]
            data = await self._post(
                "/api/wallet/ai/release",
                authorization,
                body,
            )
            if self._is_pat():
                result = data.get("hold")
                if (
                    not isinstance(result, dict)
                    or result.get("hold_no") != hold.hold_no
                    or result.get("status") != "released"
                ):
                    raise HTTPException(502, "模型释放响应无效")

    async def _post(self, path: str, authorization: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if not authorization:
            raise HTTPException(401, "缺少登录令牌，无法完成钱包扣费")
        from modstore_server.infrastructure.http_clients import get_java_client

        try:
            if self._is_pat():
                from modstore_server.llm_wallet_assertion import issue_assertion, load_signing_key

                operation = path.rsplit("/", 1)[-1]
                payload = json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
                try:
                    private_key = load_signing_key(
                        os.environ["MODSTORE_LLM_WALLET_SIGNING_KEY_PATH"]
                    )
                    token = issue_assertion(
                        private_key,
                        key_id=os.environ["MODSTORE_LLM_WALLET_KEY_ID"],
                        user_id=self.request.state.llm_pat_user_id,
                        operation=operation,
                        request_digest=hashlib.sha256(payload).hexdigest(),
                        max_amount_cents=int(os.environ["MODSTORE_LLM_WALLET_MAX_CENTS"]),
                        reservation_id=body.get("hold_no"),
                    )
                except (OSError, ValueError, KeyError, TypeError, jwt.PyJWTError) as error:
                    raise HTTPException(503, "模型密钥计费服务未配置") from error
                response = await get_java_client().post(
                    f"{self.gateway.target_base_url()}/api/internal/llm-wallet/{operation}",
                    headers={"X-Llm-Wallet-Assertion": token, "Content-Type": "application/json"},
                    content=payload,
                    timeout=20.0,
                )
            else:
                response = await get_java_client().post(
                    f"{self.gateway.target_base_url()}{path}",
                    headers={"Authorization": authorization, "Content-Type": "application/json"},
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
        try:
            data = response.json()
        except ValueError as error:
            if self._is_pat():
                raise HTTPException(502, "模型计费响应无效") from error
            raise
        if self._is_pat() and not isinstance(data, dict):
            raise HTTPException(502, "模型计费响应无效")
        if data.get("ok") is False:
            message = str(data.get("message") or "钱包扣费失败")
            if "余额不足" in message:
                raise HTTPException(402, message)
            raise HTTPException(503, message)
        return cast(dict[str, Any], data)
