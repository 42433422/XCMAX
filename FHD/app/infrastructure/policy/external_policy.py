"""外置策略评估：兼容 OPA / Cedar 风格 HTTP 决策接口。

默认停用，只有配置 ``XCAGI_POLICY_URL`` 时才参与风险门决策。本模块只负责把
动作与安全上下文提交给外部策略服务并收敛响应；任何网络或解析失败都不向上抛
异常，而是按 ``XCAGI_POLICY_FAIL_MODE`` 降级，保证风险门本身不会因外部服务
故障而返回 500。

请求体：``{"input": {"actions": [...], "context": {...}}}``
期望响应：``{"result": {"allow": bool, "require_approval": bool, "reason": str}}``
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 2.0
FAIL_MODE_OPEN = "open"
FAIL_MODE_CLOSED = "closed"
# 只允许这些非敏感字段出境；token、密钥与用户隐私一律不传
SAFE_CONTEXT_FIELDS = ("tenant_id", "mod_id", "actor_role", "ui_surface")
_UNAVAILABLE_REASON = "策略服务不可用"


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def policy_enabled() -> bool:
    """是否启用外置策略评估；未配置 URL 时保持内置决策。"""
    return bool(_env("XCAGI_POLICY_URL"))


def policy_timeout() -> float:
    """读取超时秒数；缺失、非法或非正数时回落到默认 2 秒。"""
    raw = _env("XCAGI_POLICY_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def policy_fail_mode() -> str:
    """读取失败模式；仅接受 open/closed，其余配置按 open 处理。"""
    raw = _env("XCAGI_POLICY_FAIL_MODE").lower()
    return FAIL_MODE_CLOSED if raw == FAIL_MODE_CLOSED else FAIL_MODE_OPEN


def safe_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """过滤 context，只保留允许出境的安全标量字段。"""
    raw = dict(context or {})
    safe: dict[str, Any] = {}
    for key in SAFE_CONTEXT_FIELDS:
        value = raw.get(key)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            safe[key] = value
    return safe


def _degrade(exc: Exception) -> dict[str, Any] | None:
    mode = policy_fail_mode()
    logger.warning("外置策略评估失败（fail_mode=%s）：%s", mode, exc)
    if mode == FAIL_MODE_CLOSED:
        return {"allow": False, "require_approval": False, "reason": _UNAVAILABLE_REASON}
    return None


def _parse_result(body: Any) -> dict[str, Any]:
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("allow"), bool):
        raise ValueError("外置策略响应缺少 result.allow")
    return {
        "allow": result["allow"],
        "require_approval": bool(result.get("require_approval")),
        "reason": str(result.get("reason") or "").strip(),
    }


def evaluate_external_policy(*, actions: list[dict], context: dict) -> dict[str, Any] | None:
    """调用外置策略服务。

    返回 ``{"allow", "require_approval", "reason"}``；停用或 fail-open 降级时
    返回 ``None``，由调用方继续使用内置决策。
    """
    url = _env("XCAGI_POLICY_URL")
    if not url:
        return None
    headers = {"Content-Type": "application/json"}
    if token := _env("XCAGI_POLICY_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    payload = {"input": {"actions": actions, "context": safe_context(context)}}
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=policy_timeout())
        response.raise_for_status()
        return _parse_result(response.json())
    except Exception as exc:  # noqa: BLE001 - 外置策略失败必须降级，不能中断风险门
        return _degrade(exc)


__all__ = [
    "evaluate_external_policy",
    "policy_enabled",
    "policy_fail_mode",
    "policy_timeout",
    "safe_context",
]
