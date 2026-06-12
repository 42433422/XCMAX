# -*- coding: utf-8 -*-
"""员工动作风险中间件（对齐 MODstore employee_risk_middleware）。"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_HIGH_RISK_HANDLERS = frozenset({"shell_exec", "ssh_exec", "vibe_edit", "vibe_heal", "vibe_code"})
_MEDIUM_RISK_HANDLERS = frozenset(
    {"agent", "doc_sync", "openapi_tool", "fhd_business", "http_request", "webhook"}
)


def _high_risk_gate_token() -> str:
    return (
        os.environ.get("FHD_RISK_HIGH_GATE_TOKEN")
        or os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN")
        or ""
    ).strip()


def _truthy(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return False


def assess_risk(manifest: dict[str, Any], handlers: Iterable[str]) -> tuple[str, str]:
    declared = ""
    if isinstance(manifest, dict):
        ev2 = manifest.get("employee_config_v2")
        if isinstance(ev2, dict):
            declared = str(ev2.get("risk_level") or "").strip().lower()
    handler_list = [str(h or "").strip() for h in (handlers or [])]
    has_high = any(h in _HIGH_RISK_HANDLERS for h in handler_list)
    has_medium = any(h in _MEDIUM_RISK_HANDLERS for h in handler_list)
    inferred = "high" if has_high else ("medium" if has_medium else "low")
    if declared in ("low", "medium", "high"):
        order = {"low": 0, "medium": 1, "high": 2}
        if order[declared] >= order[inferred]:
            return declared, f"manifest 声明 risk_level={declared}"
        return inferred, f"handlers 推断 risk_level={inferred}（manifest 声明 {declared}，已升级）"
    return inferred, f"handlers 推断 risk_level={inferred}"


def gate_action_or_block(
    employee_id: str,
    manifest: dict[str, Any],
    handlers: Iterable[str],
    input_data: dict[str, Any],
) -> dict[str, Any]:
    _ = employee_id
    level, reason = assess_risk(manifest or {}, handlers)
    payload = input_data or {}
    if level == "low":
        return {"ok": True, "risk_level": level, "reason": reason}
    if level == "medium":
        if _truthy(payload.get("allow_medium_risk")) or _truthy(payload.get("allow_high_risk_real_run")):
            return {"ok": True, "risk_level": level, "reason": reason}
        ev2 = manifest.get("employee_config_v2") if isinstance(manifest, dict) else {}
        autonomy = ev2.get("autonomy") if isinstance(ev2, dict) else {}
        if _truthy((autonomy or {}).get("medium_self_approve")):
            return {"ok": True, "risk_level": level, "reason": reason + "; medium_self_approve=true"}
        return _blocked(level, reason, "medium 风险需 allow_medium_risk=True")
    token_required = _high_risk_gate_token()
    token_provided = str(payload.get("high_risk_gate_token") or "").strip()
    if _truthy(payload.get("allow_high_risk_real_run")):
        if not token_required:
            return {"ok": True, "risk_level": level, "reason": reason + "; allow_high_risk_real_run=true"}
        if token_provided and token_provided == token_required:
            return {"ok": True, "risk_level": level, "reason": reason + "; gate token 校验通过"}
        return _blocked(level, reason, "high 风险需匹配 high_risk_gate_token")
    return _blocked(level, reason, "high 风险需 allow_high_risk_real_run=true")


def _blocked(level: str, reason: str, detail: str) -> dict[str, Any]:
    logger.warning("risk middleware blocked: level=%s reason=%s detail=%s", level, reason, detail)
    return {
        "ok": False,
        "blocked": True,
        "risk_level": level,
        "reason": reason,
        "detail": detail,
    }


__all__ = ["assess_risk", "gate_action_or_block"]
