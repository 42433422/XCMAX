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

    def chat(self, message: str) -> tuple[dict[str, Any], int]:
        """转发消息到外部 OpenClaw 网关，返回 (payload, status_code)。"""
        base = self._base_url().rstrip("/")
        target_url = f"{base}/api/chat"
        payload = json.dumps({"message": message}).encode("utf-8")
        req = urllib.request.Request(
            target_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self._opener(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except RECOVERABLE_ERRORS:
                    parsed = {"raw": raw}
                return ({"success": True, "target": target_url, "data": parsed}, 200)
        except urllib.error.HTTPError as err:
            with err:
                return (
                    {
                        "success": False,
                        "target": target_url,
                        "status_code": err.code,
                        "message": "上游服务请求失败",
                    },
                    502,
                )
        except RECOVERABLE_ERRORS:
            return ({"success": False, "target": target_url, "message": "上游服务请求失败"}, 502)
