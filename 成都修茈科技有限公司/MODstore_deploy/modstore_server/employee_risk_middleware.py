"""员工动作风险中间件：在 ``execute_employee_task`` 入口按 ``risk_level`` 闸门。

职责
----

- 把 manifest / handlers 列表映射成一个综合 ``risk_level``：``low`` / ``medium`` / ``high``
- 根据 ``input_data`` / 环境变量决定是否放行：
  - ``low``  始终放行
  - ``medium`` 需要 ``input_data.allow_medium_risk=True`` 或 manifest 显式声明 medium 自治
  - ``high`` 需要 ``input_data.allow_high_risk_real_run=True``，或携带匹配
    ``MODSTORE_RISK_HIGH_GATE_TOKEN`` 的 ``input_data.high_risk_gate_token``

设计要点
--------

- 这是一个"前置校验"层；与 ``auto_approve_policy.evaluate_risk``（针对单条 CR
  内容的事后评估）互补。两者关注的对象不同：本中间件针对 *executor 即将执行
  的 actions*，而 auto_approve 针对 *已经产生的 CR*。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, Tuple

logger = logging.getLogger(__name__)


_HIGH_RISK_HANDLERS = frozenset({"shell_exec", "ssh_exec", "vibe_edit", "vibe_heal", "vibe_code"})
_MEDIUM_RISK_HANDLERS = frozenset(
    {"agent", "doc_sync", "openapi_tool", "fhd_business", "http_request", "webhook"}
)


def _high_risk_gate_token() -> str:
    return (os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN") or "").strip()


def _truthy(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return False


def assess_risk(manifest: Dict[str, Any], handlers: Iterable[str]) -> Tuple[str, str]:
    """计算综合 ``risk_level``，并返回 ``(level, reason)``。

    优先级：manifest.employee_config_v2.risk_level > handlers 推断 > "low"。
    """
    declared = ""
    if isinstance(manifest, dict):
        ev2 = (
            manifest.get("employee_config_v2")
            if isinstance(manifest.get("employee_config_v2"), dict)
            else {}
        )
        declared = str((ev2 or {}).get("risk_level") or "").strip().lower()

    handler_list = [str(h or "").strip() for h in (handlers or [])]
    has_high = any(h in _HIGH_RISK_HANDLERS for h in handler_list)
    has_medium = any(h in _MEDIUM_RISK_HANDLERS for h in handler_list)

    inferred = "high" if has_high else ("medium" if has_medium else "low")

    if declared in ("low", "medium", "high"):
        # manifest 声明的等级与推断取较高者，避免低估
        order = {"low": 0, "medium": 1, "high": 2}
        if order[declared] >= order[inferred]:
            return declared, f"manifest 声明 risk_level={declared}"
        return inferred, f"handlers 推断 risk_level={inferred}（manifest 声明 {declared}，已升级）"

    return inferred, f"handlers 推断 risk_level={inferred}"


def gate_action_or_block(
    employee_id: str,
    manifest: Dict[str, Any],
    handlers: Iterable[str],
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """返回 ``{"ok": True}`` 表示放行；否则 ``{"ok": False, "blocked": True, ...}``。"""
    level, reason = assess_risk(manifest or {}, handlers)
    payload = input_data or {}

    if level == "low":
        return {"ok": True, "risk_level": level, "reason": reason}

    if level == "medium":
        if _truthy(payload.get("allow_medium_risk")) or _truthy(
            payload.get("allow_high_risk_real_run")
        ):
            return {"ok": True, "risk_level": level, "reason": reason}
        # manifest 自治声明：employee_config_v2.autonomy.medium_self_approve = true
        try:
            ev2 = manifest.get("employee_config_v2") if isinstance(manifest, dict) else {}
            if _truthy(((ev2 or {}).get("autonomy") or {}).get("medium_self_approve")):
                return {
                    "ok": True,
                    "risk_level": level,
                    "reason": reason + "; medium_self_approve=true",
                }
        except Exception:
            pass
        return _blocked(
            level,
            reason,
            "medium 风险需 allow_medium_risk=True 或 manifest.autonomy.medium_self_approve=true",
        )

    # high
    token_required = _high_risk_gate_token()
    token_provided = str(payload.get("high_risk_gate_token") or "").strip()
    if _truthy(payload.get("allow_high_risk_real_run")):
        if not token_required:
            return {
                "ok": True,
                "risk_level": level,
                "reason": reason + "; allow_high_risk_real_run=true",
            }
        if token_provided and token_provided == token_required:
            return {"ok": True, "risk_level": level, "reason": reason + "; gate token 校验通过"}
        return _blocked(
            level,
            reason,
            "high 风险已设置 MODSTORE_RISK_HIGH_GATE_TOKEN：必须提供匹配 high_risk_gate_token",
        )
    return _blocked(level, reason, "high 风险需 allow_high_risk_real_run=true 才能执行")


def _blocked(level: str, reason: str, detail: str) -> Dict[str, Any]:
    logger.warning("risk middleware blocked: level=%s reason=%s detail=%s", level, reason, detail)
    return {
        "ok": False,
        "blocked": True,
        "risk_level": level,
        "reason": reason,
        "detail": detail,
    }


__all__ = ["assess_risk", "gate_action_or_block"]
