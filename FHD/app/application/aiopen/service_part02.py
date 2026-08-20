# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.aiopen.service")


def openclaw_chat_proxy(message: str) -> tuple[dict[str, _facade().Any], int]:
    """转发消息到外部 OpenClaw 网关，返回 (payload, status_code)。"""
    base = str(_facade().AIOPEN_STATE.get("openclaw_base", "http://localhost:28789")).rstrip("/")
    target_url = f"{base}/api/chat"
    payload = _facade().json.dumps({"message": message}).encode("utf-8")
    req = _facade().urllib.request.Request(
        target_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with _facade().urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = _facade().json.loads(raw) if raw else {}
            except _facade().RECOVERABLE_ERRORS:
                parsed = {"raw": raw}
            return ({"success": True, "target": target_url, "data": parsed}, 200)
    except _facade().urllib.error.HTTPError as err:
        return (
            {
                "success": False,
                "target": target_url,
                "status_code": err.code,
                "message": "上游服务请求失败",
            },
            502,
        )
    except _facade().RECOVERABLE_ERRORS:
        return ({"success": False, "target": target_url, "message": "上游服务请求失败"}, 502)
