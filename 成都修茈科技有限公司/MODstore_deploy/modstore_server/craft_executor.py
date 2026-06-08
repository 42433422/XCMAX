from __future__ import annotations

import logging
import time
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger(__name__)

CRAFT_STEP_EMPLOYEE_MAP: Dict[str, str] = {
    "spec": "intent-analyst",
    "employee_plan": "employee-planner",
    "generate": "artifact-generator",
    "validate": "quality-validator",
    "script_workflow": "miniapp-builder",
    "embed_script": "script-binder",
    "workflow": "workflow-automator",
    "register_pack": "pack-registrar",
    "workflow_sandbox": "sandbox-tester",
    "mod_sandbox": "code-validator",
    "standalone_smoke": "self-checker",
    "host_check": "host-checker",
    "six_dim_gate": "hex-quality-assessor",
}

EMPLOYEE_TO_CRAFT_STEP: Dict[str, str] = {v: k for k, v in CRAFT_STEP_EMPLOYEE_MAP.items()}

CRAFT_PIPELINE_ORDER: list[str] = [
    "intent-analyst",
    "employee-planner",
    "artifact-generator",
    "quality-validator",
    "miniapp-builder",
    "script-binder",
    "workflow-automator",
    "pack-registrar",
    "sandbox-tester",
    "code-validator",
    "self-checker",
    "host-checker",
    "hex-quality-assessor",
]

_step_registry: Dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}


def register_craft_step(step_id: str, fn: Callable[..., Coroutine[Any, Any, Any]]) -> None:
    _step_registry[step_id] = fn


def craft_step_to_employee_id(step_id: str) -> Optional[str]:
    return CRAFT_STEP_EMPLOYEE_MAP.get(step_id)


def employee_id_to_craft_step(employee_id: str) -> Optional[str]:
    return EMPLOYEE_TO_CRAFT_STEP.get(employee_id)


def is_craft_employee(employee_id: str) -> bool:
    return employee_id in EMPLOYEE_TO_CRAFT_STEP


def craft_pipeline_order() -> list[str]:
    return list(CRAFT_PIPELINE_ORDER)


def craft_employee_depends_on(employee_id: str) -> Optional[str]:
    idx = CRAFT_PIPELINE_ORDER.index(employee_id) if employee_id in CRAFT_PIPELINE_ORDER else -1
    if idx > 0:
        return CRAFT_PIPELINE_ORDER[idx - 1]
    return None


async def dispatch_craft_step(
    step_id: str,
    **kwargs: Any,
) -> Any:
    from modstore_server.craft_failure_signals import emit_craft_step_failure, resolve_craft_step_id

    resolved_step, employee_id = resolve_craft_step_id(step_id)
    fn = _step_registry.get(resolved_step)

    if not fn:
        msg = f"未注册的 craft 步骤：{step_id!r}（解析为 {resolved_step!r}）"
        logger.warning("dispatch_craft_step: %s", msg)
        emit_craft_step_failure(
            step_id=resolved_step or step_id,
            error=msg,
            employee_id=employee_id,
            user_id=int(kwargs.get("user_id") or 0),
        )
        return {
            "ok": False,
            "status": "fail",
            "summary": msg[:400],
            "error": msg,
        }

    t0 = time.monotonic()
    try:
        result = await fn(**kwargs)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if employee_id:
            _record_craft_execution(
                employee_id=employee_id,
                user_id=kwargs.get("user_id", 0),
                task=f"craft pipeline step: {resolved_step}",
                status="success",
                duration_ms=elapsed_ms,
                llm_tokens=0,
            )
        if isinstance(result, dict) and result.get("report") is not None:
            report = result["report"]
            if isinstance(report, dict) and not report.get("ok"):
                err_parts = list(report.get("errors") or [])
                summary = str(report.get("summary") or "").strip()
                if summary and summary not in err_parts:
                    err_parts.insert(0, summary)
                emit_craft_step_failure(
                    step_id=resolved_step,
                    error="；".join(str(e) for e in err_parts[:3])
                    or summary
                    or "workflow 沙箱校验失败",
                    employee_id=employee_id,
                    user_id=int(kwargs.get("user_id") or 0),
                    duration_ms=elapsed_ms,
                    extra={
                        "workflow_id": report.get("workflow_id"),
                        "sandbox_report": report,
                    },
                )
        return result
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        emit_craft_step_failure(
            step_id=resolved_step,
            error=str(exc),
            employee_id=employee_id,
            user_id=int(kwargs.get("user_id") or 0),
            duration_ms=elapsed_ms,
        )
        raise


def _record_craft_execution(
    *,
    employee_id: str,
    user_id: int,
    task: str,
    status: str,
    duration_ms: int,
    llm_tokens: int,
    error: str = "",
) -> None:
    try:
        from modstore_server.db.base import get_session_factory
        from modstore_server.models import EmployeeExecutionMetric

        sf = get_session_factory()
        with sf() as session:
            session.add(
                EmployeeExecutionMetric(
                    user_id=user_id,
                    employee_id=employee_id,
                    task=task[:500],
                    status=status,
                    duration_ms=duration_ms,
                    llm_tokens=llm_tokens,
                    error=(error or "")[:1000],
                )
            )
            session.commit()
    except Exception:
        logger.debug("craft execution record failed for %s", employee_id, exc_info=True)
