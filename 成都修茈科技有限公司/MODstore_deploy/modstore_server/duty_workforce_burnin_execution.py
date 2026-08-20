# mypy: disable-error-code="arg-type, assignment, union-attr"
"""Validation and bounded execution for duty-workforce burn-in."""

from __future__ import annotations

import importlib
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, Optional

from modstore_server.duty_workforce_burnin_constants import (
    READ_ONLY_AGENT_TOOLS as _READ_ONLY_AGENT_TOOLS,
)
from modstore_server.duty_workforce_burnin_constants import (
    READ_ONLY_OBSERVATION_TOOLS as _READ_ONLY_OBSERVATION_TOOLS,
)
from modstore_server.models import EmployeeExecutionMetric, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.duty_workforce_burnin")


def validate_burn_in_execution_result(execution: Dict[str, Any]) -> Dict[str, Any]:
    """Strict acceptance gate shared by the executor and burn-in orchestrator."""
    reasons: list[str] = []
    if not isinstance(execution, dict):
        return {"passed": False, "reasons": ["execution_not_object"]}
    if execution.get("handler_failed"):
        reasons.append("executor_handler_failed")
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    verification = (
        result.get("verification") if isinstance(result.get("verification"), dict) else {}
    )
    if verification.get("passed") is not True:
        reasons.append("programmatic_verification_failed")
    outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
    agent_outputs = [
        item for item in outputs if isinstance(item, dict) and item.get("handler") == "agent"
    ]
    direct_outputs = [
        item
        for item in outputs
        if isinstance(item, dict) and item.get("handler") == "direct_python"
    ]
    if not agent_outputs and (not direct_outputs):
        reasons.append("no_capability_output")
    for output in outputs:
        if not isinstance(output, dict):
            reasons.append("invalid_handler_output")
            continue
        if output.get("ok") is False or str(output.get("error") or "").strip():
            reasons.append(f"handler_failed:{output.get('handler') or '?'}")
    for output in agent_outputs:
        kinds = {str(item) for item in output.get("tool_call_kinds") or [] if str(item)}
        if not kinds.intersection(_READ_ONLY_OBSERVATION_TOOLS):
            reasons.append("no_successful_read_only_observation")
        if not kinds.issubset(_READ_ONLY_AGENT_TOOLS):
            reasons.append("non_read_only_tool_attempted")
        if int(output.get("tool_call_success_count") or 0) < 1:
            reasons.append("no_successful_tool_call")
        if output.get("change_request_ids"):
            reasons.append("change_request_created")
    for output in direct_outputs:
        body = output.get("output") if isinstance(output.get("output"), dict) else {}
        status = str(body.get("status") or "").strip().lower()
        summary = str(body.get("summary") or "").strip()
        evidence = body.get("evidence") if isinstance(body.get("evidence"), list) else []
        if body.get("ok") is not True:
            reasons.append("direct_python_output_not_ok")
        if status not in {"success", "approved", "completed"}:
            reasons.append("direct_python_status_not_success")
        if len(summary) < 10:
            reasons.append("direct_python_summary_missing")
        if not evidence:
            reasons.append("direct_python_evidence_missing")
        if body.get("read_only") is not True:
            reasons.append("direct_python_not_read_only")
        if body.get("side_effects") != []:
            reasons.append("direct_python_side_effects_present")
    bridge = (
        result.get("change_request_bridge")
        if isinstance(result.get("change_request_bridge"), dict)
        else {}
    )
    if bridge and bridge.get("suppressed") is not True:
        reasons.append("change_request_bridge_not_suppressed")
    if execution.get("change_request_ids") or result.get("change_request_ids"):
        reasons.append("change_request_created")
    unique = list(dict.fromkeys(reasons))
    tool_kinds = sorted(
        {
            str(kind)
            for output in agent_outputs
            for kind in output.get("tool_call_kinds") or []
            if str(kind)
        }
    )
    return {
        "passed": not unique,
        "reasons": unique,
        "verification": {
            "passed": verification.get("passed") is True,
            "summary": str(verification.get("summary") or "")[:500],
        },
        "agent_observation_count": len(agent_outputs),
        "direct_python_receipt_count": len(direct_outputs),
        "tool_call_kinds": tool_kinds,
        "tool_call_success_count": sum(
            (int(output.get("tool_call_success_count") or 0) for output in agent_outputs)
        ),
        "tool_call_failure_count": sum(
            (int(output.get("tool_call_failure_count") or 0) for output in agent_outputs)
        ),
    }


def _mark_receipt_rejected(employee_id: str, marker: str, status: str, reason: str) -> bool:
    """Invalidate only the metric emitted for this exact burn-in marker."""
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(EmployeeExecutionMetric)
            .filter(
                EmployeeExecutionMetric.employee_id == employee_id,
                EmployeeExecutionMetric.task.like(f"{marker}%"),
                EmployeeExecutionMetric.status.in_(["success", "completed"]),
            )
            .order_by(EmployeeExecutionMetric.id.desc())
            .first()
        )
        if row is None:
            return False
        row.status = str(status or "burnin_rejected")[:32]
        row.error = str(reason or "burn-in acceptance rejected")[:4000]
        session.commit()
        return True


def _project_root() -> str:
    try:
        from modstore_server.workflow_scheduler import _employee_project_root

        return str(_employee_project_root() or "")
    except RECOVERABLE_ERRORS:
        return ""


def _execute_one(
    candidate: Dict[str, Any],
    *,
    run_id: str,
    deadline_epoch: float,
    executor: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    employee_id = str(candidate["employee_id"])
    marker = f"[duty-burn-in:{run_id}:{employee_id}]"
    contract = {
        "employee_id": employee_id,
        "mission": candidate.get("mission"),
        "mode": candidate.get("mode"),
        "risk_level": candidate.get("risk_level"),
        "acceptance": list(candidate.get("acceptance") or []),
    }
    task = _facade()._candidate_task(employee_id, contract, marker)
    if "direct_python" in candidate.get("capability_handlers", []):
        task = _facade()._candidate_direct_task(employee_id, marker)
    project_root = _facade()._project_root()
    from modstore_server.services.llm import resolve_platform_bench_llm

    provider, model = resolve_platform_bench_llm()
    payload: Dict[str, Any] = {
        "trigger": "duty_workforce_burn_in",
        "burn_in": True,
        "burn_in_read_only": True,
        "burn_in_deadline_epoch": float(deadline_epoch),
        "suppress_employee_im": True,
        "suppress_handoff": True,
        "suppress_human_questions": True,
        "suppress_change_requests": True,
        "suppress_lifecycle_events": True,
        "im_reply_managed": True,
        "non_blocking_human_questions": True,
        "allow_medium_risk": False,
        "allow_high_risk": False,
        "allow_high_risk_real_run": False,
        "handler_mode": "agent",
        "multi_step": True,
        "work_contract": contract,
    }
    fixture = (
        candidate.get("burn_in_fixture")
        if isinstance(candidate.get("burn_in_fixture"), dict)
        else {}
    )
    if "direct_python" in candidate.get("capability_handlers", []):
        payload.update(fixture)
        payload["handler"] = "direct_python"
        payload["handler_mode"] = "direct_python"
        payload["multi_step"] = False
    if project_root:
        payload["project_root"] = project_root
    try:
        execution = executor(
            employee_id,
            task,
            payload,
            user_id=0,
            bench_llm_override=(provider, model) if provider and model else None,
        )
    except RECOVERABLE_ERRORS as exc:
        return {
            "employee_id": employee_id,
            "marker": marker,
            "status": "failed",
            "receipt_accepted": False,
            "manifest_sha256": str(candidate.get("manifest_sha256") or ""),
            "contract_sha256": str(candidate.get("contract_sha256") or ""),
            "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
        }
    acceptance = _facade().validate_burn_in_execution_result(execution)
    if not acceptance["passed"]:
        reason = ";".join(acceptance["reasons"])[:1000]
        _facade()._mark_receipt_rejected(employee_id, marker, "burnin_rejected", reason)
        status = "rejected"
    else:
        status = "accepted"
    return {
        "employee_id": employee_id,
        "marker": marker,
        "status": status,
        "receipt_accepted": bool(acceptance["passed"]),
        "manifest_sha256": str(candidate.get("manifest_sha256") or ""),
        "contract_sha256": str(candidate.get("contract_sha256") or ""),
        "acceptance": acceptance,
        "duration_ms": execution.get("duration_ms"),
        "executed_at": execution.get("executed_at"),
    }


def run_burn_in(
    *,
    dry_run: bool = True,
    window_hours: int = 24,
    limit: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
    max_concurrency: Optional[int] = None,
    _plan: Optional[Dict[str, Any]] = None,
    _executor: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Plan or execute one bounded burn-in wave.

    ``dry_run=False`` still cannot execute unless
    ``MODSTORE_EMPLOYEE_BURN_IN_ENABLED=1`` is present in the effective runtime.
    """
    plan = _plan or _facade().build_burn_in_plan(window_hours=window_hours, limit=limit)
    if dry_run:
        return plan
    if not _facade().burn_in_execution_enabled():
        return {
            **plan,
            "dry_run": True,
            "execution_blocked": True,
            "blocked_reason": "MODSTORE_EMPLOYEE_BURN_IN_ENABLED is not enabled",
        }
    if not _facade()._run_lock.acquire(blocking=False):
        return {
            **plan,
            "dry_run": False,
            "executed": False,
            "reason": "already_running",
        }
    lingering = _facade()._lingering_execution_count()
    if lingering:
        _facade()._run_lock.release()
        return {
            **plan,
            "dry_run": False,
            "executed": False,
            "reason": "previous_timeout_still_running",
            "lingering_execution_count": lingering,
        }
    limits = _facade().burn_in_limits()
    timeout = max(30, min(int(timeout_seconds or limits["timeout_seconds"]), 300))
    concurrency = max(1, min(int(max_concurrency or limits["max_concurrency"]), 2))
    selected = list(plan.get("candidates") or [])[: limits["max_candidates"]]
    run_id = uuid.uuid4().hex[:12]
    results: list[Dict[str, Any]] = []
    executor_fn = _executor
    if executor_fn is None:
        from modstore_server.employee_executor import execute_employee_task

        executor_fn = execute_employee_task
    try:
        for start in range(0, len(selected), concurrency):
            batch = selected[start : start + concurrency]
            pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="duty-burn-in")
            futures: Dict[Future[Dict[str, Any]], Dict[str, Any]] = {
                pool.submit(
                    _facade()._execute_one,
                    item,
                    run_id=run_id,
                    deadline_epoch=time.time() + timeout,
                    executor=executor_fn,
                ): item
                for item in batch
            }
            done, pending = wait(set(futures), timeout=timeout)
            for future in done:
                item = futures[future]
                try:
                    row = future.result()
                except RECOVERABLE_ERRORS as exc:
                    row = {
                        "employee_id": str(item.get("employee_id") or ""),
                        "status": "failed",
                        "receipt_accepted": False,
                        "error": f"orchestrator:{type(exc).__name__}:{str(exc)[:500]}",
                    }
                results.append(row)
                _facade()._append_audit({"run_id": run_id, **row})
            for future in pending:
                item = futures[future]
                employee_id = str(item.get("employee_id") or "")
                marker = f"[duty-burn-in:{run_id}:{employee_id}]"
                future.cancel()
                if not future.done():
                    _facade()._track_lingering_future(future)
                invalidated = _facade()._mark_receipt_rejected(
                    employee_id,
                    marker,
                    "burnin_timeout",
                    f"burn-in exceeded {timeout}s",
                )
                row = {
                    "employee_id": employee_id,
                    "marker": marker,
                    "status": "timeout",
                    "receipt_accepted": False,
                    "manifest_sha256": str(item.get("manifest_sha256") or ""),
                    "contract_sha256": str(item.get("contract_sha256") or ""),
                    "timeout_seconds": timeout,
                    "success_metric_invalidated": invalidated,
                }
                results.append(row)
                _facade()._append_audit({"run_id": run_id, **row})
            pool.shutdown(wait=False, cancel_futures=True)
    finally:
        _facade()._run_lock.release()
    accepted = sum((1 for item in results if item.get("receipt_accepted") is True))
    summary = {
        "ok": accepted == len(results),
        "dry_run": False,
        "executed": True,
        "run_id": run_id,
        "selected_count": len(selected),
        "completed_count": len(results),
        "accepted_receipt_count": accepted,
        "rejected_or_failed_count": len(results) - accepted,
        "results": sorted(results, key=lambda item: str(item.get("employee_id") or "")),
        "limits": {
            **limits,
            "timeout_seconds": timeout,
            "max_concurrency": concurrency,
        },
        "audit_path": str(_facade().burn_in_audit_path()),
    }
    _facade()._append_audit(
        {
            "run_id": run_id,
            "record_type": "run_summary",
            "selected_count": len(selected),
            "accepted_receipt_count": accepted,
            "rejected_or_failed_count": len(results) - accepted,
        }
    )
    return summary
