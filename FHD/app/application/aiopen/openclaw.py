"""OpenClaw upstream proxy with an explicit opener and response lifetime."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import UpstreamOpener


class OpenClawProxy:
    def __init__(self, base_url: Callable[[], str], opener: UpstreamOpener) -> None:
        self._base_url = base_url
        self._opener = opener

    def chat(self, message: str, *, request_id: str, gateway_url: str) -> dict[str, Any]:
        """Send the approved target once; an HTTP reply is only an observation."""
        base = gateway_url.strip().rstrip("/")
        if (
            not message.strip()
            or not request_id
            or not base
            or base != self._base_url().rstrip("/")
        ):
            return {
                "success": False,
                "error_code": "openclaw_request_invalid",
                "execution_state": "not_started",
                "retryable": False,
                "message": "消息、请求标识或已审批的网关地址不一致，未发送。",
            }
        target_url = f"{base}/api/chat"
        payload = json.dumps({"message": message}).encode("utf-8")
        req = urllib.request.Request(
            target_url,
            data=payload,
            headers={"Content-Type": "application/json", "Idempotency-Key": request_id},
            method="POST",
        )
        receipt: dict[str, Any] = {
            "success": False,
            "target": target_url,
            "execution_state": "unknown",
            "retryable": False,
            "reconciliation_required": True,
            "error_code": "openclaw_result_unverified",
            "message": "OpenClaw 请求结果待核验，请查询原任务，勿重复发送。",
        }
        try:
            with self._opener(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except RECOVERABLE_ERRORS:
                    parsed = {"raw": raw}
                return {**receipt, "transport_accepted": True, "observation": parsed}
        except urllib.error.HTTPError as err:
            with err:
                return {**receipt, "upstream_status_code": err.code}
        except RECOVERABLE_ERRORS:
            return receipt
