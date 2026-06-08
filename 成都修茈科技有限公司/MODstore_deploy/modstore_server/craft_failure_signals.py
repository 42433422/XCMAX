"""制作车间 craft 步骤失败：指标、incident-bus（on_error）、可选人工升级。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def resolve_craft_step_id(step_or_employee: str) -> Tuple[str, Optional[str]]:
    """将 craft 步骤 id 或员工 id 解析为 (step_id, employee_id)。"""
    from modstore_server.craft_executor import (
        craft_step_to_employee_id,
        employee_id_to_craft_step,
    )

    key = str(step_or_employee or "").strip()
    if not key:
        return "", None
    if employee_id_to_craft_step(key):
        return employee_id_to_craft_step(key) or key, key
    emp = craft_step_to_employee_id(key)
    return key, emp


def _load_yuangon_employee_meta(employee_id: str) -> Dict[str, Any]:
    try:
        from modstore_server.all_hands_report import _load_yuangon_employee_meta as _load

        return _load(employee_id)
    except Exception:  # noqa: BLE001
        return {}


def _employee_escalate_to_human(employee_id: str) -> bool:
    """读取 yuangon employee.yaml 中 sla.escalate_to_human。"""
    if not employee_id:
        return False
    sla = _load_yuangon_employee_meta(employee_id).get("sla")
    if isinstance(sla, dict):
        return bool(sla.get("escalate_to_human"))
    return False


def _employee_trigger_limits(employee_id: str) -> Dict[str, int]:
    """读取 yuangon employee.yaml triggers 中的动态修复预算。"""
    trig = _load_yuangon_employee_meta(employee_id).get("triggers")
    if not isinstance(trig, dict):
        return {"max_patch_budget_tokens": 3000, "max_patch_steps": 4}
    try:
        budget = int(trig.get("max_patch_budget_tokens") or 3000)
    except (TypeError, ValueError):
        budget = 3000
    try:
        steps = int(trig.get("max_patch_steps") or 4)
    except (TypeError, ValueError):
        steps = 4
    return {"max_patch_budget_tokens": max(500, budget), "max_patch_steps": max(1, steps)}


def invalid_workflow_sandbox_report(workflow_id: Any) -> Dict[str, Any]:
    """skill-sandbox-testing 约定的失败报告（缺/无效 workflow_id）。"""
    wid = str(workflow_id).strip() if workflow_id is not None else ""
    detail = (
        f"收到 workflow_id={wid!r}，须为正整数。"
        "请确认 pack-registrar / workflow-automator 已创建画布工作流并传入 workflow_id。"
    )
    return {
        "ok": False,
        "status": "fail",
        "summary": "输入 workflow_id 无效",
        "workflow_id": wid,
        "structure_validation": {"status": "fail", "errors": [detail]},
        "mock_execution": {"status": "skipped", "phases_run": 0, "errors": []},
        "employee_reachability": {"status": "skipped", "unreachable": []},
        "errors": [detail],
        "warnings": [],
        "steps": [],
        "output": {},
        "validate_only": True,
    }


def emit_craft_step_failure(
    *,
    step_id: str,
    error: str,
    employee_id: Optional[str] = None,
    user_id: int = 0,
    duration_ms: int = 0,
    llm_tokens: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """记录失败指标并发布 on_error（含 escalate_to_human 标记供下游消费）。"""
    resolved_step, resolved_emp = resolve_craft_step_id(step_id)
    emp = (employee_id or resolved_emp or "").strip()
    msg = (error or "craft 步骤失败").strip()[:1000]
    if not msg:
        msg = "craft 步骤失败（未提供错误详情）"

    try:
        from modstore_server.craft_executor import _record_craft_execution

        if emp:
            _record_craft_execution(
                employee_id=emp,
                user_id=int(user_id or 0),
                task=f"craft pipeline step: {resolved_step or step_id}",
                status="error",
                duration_ms=duration_ms,
                llm_tokens=llm_tokens,
                error=msg,
            )
    except Exception:
        logger.debug("craft failure metric record failed step=%s", step_id, exc_info=True)

    escalate = _employee_escalate_to_human(emp) if emp else False
    payload: Dict[str, Any] = {
        "summary": msg[:500],
        "craft_step": resolved_step or step_id,
        "employee_id": emp,
        "escalate_to_human": escalate,
    }
    if extra:
        payload.update(extra)

    try:
        from modstore_server.incident_bus import publish

        publish(
            "on_error",
            payload,
            source=emp or (resolved_step or step_id),
        )
    except Exception:
        logger.exception("craft step on_error publish failed step=%s", step_id)

    if emp:
        try:
            from modstore_server.services.change_signal import emit_task_lifecycle_event

            emit_task_lifecycle_event(
                emp,
                f"craft:{resolved_step or step_id}",
                status="failed",
                error=msg,
            )
        except Exception:
            logger.debug("craft failure lifecycle event failed", exc_info=True)
